"""
A live conversation with Vikki.

Runs five concurrent tasks for the lifetime of the session:
  * camera     - shows the live preview window and queues a frame for sending every few seconds
  * microphone - streams mic audio, muted while Vikki speaks except for barge-in
  * sender     - forwards queued audio/video to the live session
  * receiver   - plays Vikki's replies, handles interruptions, records the conversation
  * speaker    - plays Vikki's audio

All work is wrapped in try/except; failures are logged and end the session cleanly.
"""

import asyncio
import collections
from datetime import datetime

import numpy as np
from google import genai
from google.genai import types

from vikki_vision.assistant.client import build_live_config
from vikki_vision.audio import microphone as mic_module
from vikki_vision.audio.barge_in import BargeInDetector, rms
from vikki_vision.audio.microphone import Microphone
from vikki_vision.audio.speaker import Speaker
from vikki_vision.config import Settings
from vikki_vision.storage.session_store import SessionRecorder
from vikki_vision.utils.logger import get_logger
from vikki_vision.vision.camera import Camera

log = get_logger(__name__)

OUT_QUEUE_SIZE = 5
CAMERA_POLL_SECONDS = 0.1  # how often to check whether the preview window was closed
PREROLL_CHUNKS = 8  # ~0.5 s of muted mic audio sent on barge-in so Vikki hears the whole phrase


class UserQuit(Exception):
    """The user closed the preview window."""


class VikkiSession:
    def __init__(self, settings: Settings, client: genai.Client):
        self.settings = settings
        self.client = client
        self.name = settings.assistant_name

        self.camera = Camera(settings.camera_index, show_preview=settings.show_preview)
        self.microphone = Microphone()
        self.speaker: Speaker | None = None
        self.barge_in = BargeInDetector(min_rms=settings.barge_in_min_rms)
        self.recorder: SessionRecorder | None = None

        self.session = None
        self.out_queue: asyncio.Queue | None = None
        self.user_turn_ended = False

    # ---------- outgoing ----------

    def _status_text(self) -> str:
        if self.speaker is not None and self.speaker.is_speaking():
            return f"{self.name} is speaking"
        return f"{self.name} is listening"

    def _capture_frame(self) -> bytes | None:
        """Grab the latest frame as JPEG and save it to the session recording (runs in a worker thread)."""
        try:
            jpeg = self.camera.latest_jpeg()
            if jpeg is not None and self.recorder is not None:
                self.recorder.save_frame(jpeg)
            return jpeg
        except Exception:
            log.exception("Failed to read camera frame")
            return None

    async def stream_camera(self):
        try:
            # Opening the camera can take several seconds; keep it off the event loop
            await asyncio.to_thread(self.camera.open)
            self.camera.start(status_text=self._status_text)
            loop = asyncio.get_running_loop()
            next_send = loop.time()
            frames_sent = 0
            while True:
                if self.camera.user_closed:
                    raise UserQuit()
                if self.camera.failed:
                    log.warning("Camera stopped delivering frames, stopping video stream")
                    break
                if loop.time() >= next_send:
                    jpeg = await asyncio.to_thread(self._capture_frame)
                    if jpeg is not None:
                        await self.out_queue.put({"video": types.Blob(data=jpeg, mime_type="image/jpeg")})
                        frames_sent += 1
                        if frames_sent % 30 == 0:
                            log.debug("Queued %d camera frames", frames_sent)
                        next_send = loop.time() + self.settings.frame_interval_seconds
                await asyncio.sleep(CAMERA_POLL_SECONDS)
        except UserQuit:
            raise
        except Exception:
            log.exception("Camera streaming failed")
            raise
        finally:
            await asyncio.to_thread(self.camera.stop)

    async def stream_microphone(self):
        try:
            self.microphone.open()
            preroll = collections.deque(maxlen=PREROLL_CHUNKS)
            muted_levels: list[float] = []
            open_mic_peak = 0.0

            while True:
                data = await self.microphone.read()
                blob = types.Blob(data=data, mime_type=mic_module.MIME_TYPE)
                level = rms(data)

                if not self.speaker.is_speaking():
                    open_mic_peak = max(open_mic_peak, level)
                    if muted_levels:
                        log.debug(
                            "Mic level while %s spoke: median=%.0f max=%.0f (barge-in threshold %.0f)",
                            self.name, float(np.median(muted_levels)), max(muted_levels), self.barge_in.threshold,
                        )
                        muted_levels = []
                    if self.user_turn_ended:
                        log.debug("Mic peak level while the user had the floor: %.0f", open_mic_peak)
                        open_mic_peak = 0.0
                        self.user_turn_ended = False
                    preroll.clear()
                    self.barge_in.reset()
                    await self.out_queue.put({"audio": blob})
                    continue

                # Vikki is speaking: don't send her own echo back to her, but watch for the user talking over her
                preroll.append(blob)
                muted_levels.append(level)
                if self.barge_in.update(level):
                    log.info("User started talking over %s (mic level %.0f) - interrupting", self.name, level)
                    self.speaker.stop()
                    while preroll:
                        await self.out_queue.put({"audio": preroll.popleft()})
        except Exception:
            log.exception("Microphone streaming failed")
            raise

    async def send_realtime(self):
        try:
            while True:
                msg = await self.out_queue.get()
                await self.session.send_realtime_input(**msg)
        except Exception:
            log.exception("Failed to send realtime input")
            raise

    # ---------- incoming ----------

    async def receive_responses(self):
        try:
            while True:
                user_said, vikki_said = [], []
                user_started = vikki_started = None
                turn_epoch = None
                async for response in self.session.receive():
                    if turn_epoch is None:
                        turn_epoch = self.speaker.epoch
                    # After a local barge-in, discard the rest of the interrupted reply
                    if (data := response.data) and self.speaker.epoch == turn_epoch:
                        self.speaker.enqueue(data)

                    content = response.server_content
                    if content is None:
                        continue
                    if content.input_transcription and content.input_transcription.text:
                        user_said.append(content.input_transcription.text)
                        user_started = user_started or datetime.now()
                    if content.output_transcription and content.output_transcription.text:
                        vikki_said.append(content.output_transcription.text)
                        vikki_started = vikki_started or datetime.now()
                    if content.interrupted:
                        dropped = self.speaker.stop()
                        log.info("%s was interrupted (dropped %d queued audio chunks)", self.name, dropped)

                # Conversation text goes to conversations/ only; the log just records that a turn happened
                if user_said:
                    self.recorder.add_message("User", "".join(user_said).strip(), user_started)
                    self.user_turn_ended = True
                if vikki_said:
                    self.recorder.add_message(self.name, "".join(vikki_said).strip(), vikki_started)
                log.info(
                    "Turn complete (user speech: %s, %s reply: %s)",
                    "yes" if user_said else "no", self.name, "yes" if vikki_said else "no",
                )
        except Exception:
            log.exception("Receiving responses failed")
            raise

    async def play_audio(self):
        try:
            self.speaker.open()
            await self.speaker.run()
        except Exception:
            log.exception("Audio playback failed")
            raise

    # ---------- lifecycle ----------

    async def run(self) -> None:
        log.info("Connecting to %s...", self.name)
        try:
            async with (
                self.client.aio.live.connect(
                    model=self.settings.model, config=build_live_config(self.settings)
                ) as session,
                asyncio.TaskGroup() as tg,
            ):
                self.session = session
                log.info("Connected - %s is live", self.name)
                self.recorder = SessionRecorder(self.settings.conversations_dir)
                self.speaker = Speaker()
                self.out_queue = asyncio.Queue(maxsize=OUT_QUEUE_SIZE)

                tg.create_task(self.send_realtime())
                tg.create_task(self.stream_microphone())
                tg.create_task(self.stream_camera())
                tg.create_task(self.receive_responses())
                tg.create_task(self.play_audio())
                log.info("Streaming camera and microphone - close the camera window or press Ctrl+C to quit")

        except asyncio.CancelledError:
            log.info("Session cancelled")
        except ExceptionGroup as eg:
            failures = [exc for exc in eg.exceptions if not isinstance(exc, UserQuit)]
            if not failures:
                log.info("User closed the camera window")
            for exc in failures:
                log.error("Task failed: %r", exc, exc_info=exc)
        except Exception:
            log.exception("Live session failed")
        finally:
            self.microphone.close()
            if self.speaker is not None:
                self.speaker.close()
            if self.recorder is not None:
                self.recorder.close()
            log.info("Session ended")
