"""
Vikki Vision - real-time camera + voice assistant.

Streams the default webcam and microphone to Vikki and plays her spoken replies,
so the whole conversation happens by voice while Vikki watches the camera.

Features:
  * audio input/output via `sounddevice`
  * the microphone is muted while Vikki is speaking so she doesn't hear herself through the
    speakers, but the user can still interrupt her by speaking louder than her echo (barge-in)
  * every event is logged via logger.py and all work is wrapped in try/except
  * the conversation (CSV) and camera frames of each session are saved via session_store.py

Usage:
    python liveAPI.py

Press Ctrl+C to quit.
"""

import asyncio
import collections
import io
import os
import sys
import time
from datetime import datetime

from logger import get_logger
from session_store import SessionRecorder

log = get_logger("liveAPI")

try:
    import cv2
    import numpy as np
    import PIL.Image
    import sounddevice as sd
    from dotenv import load_dotenv
    from google import genai
    from google.genai import types
except ImportError as e:
    log.critical("Missing dependency: %s. Run 'pip install -r requirements.txt'.", e)
    sys.exit(1)

load_dotenv()

CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024
FRAME_INTERVAL_SECONDS = 1.0
# Keep the mic muted this long after Vikki's last audio chunk, to cover speaker latency/room echo
MIC_UNMUTE_DELAY_SECONDS = 0.6

# Barge-in: while Vikki talks, the user interrupts her by speaking louder than her echo.
# A mic chunk (int16 RMS) counts as user speech when it exceeds
# max(BARGE_IN_MIN_RMS, BARGE_IN_ECHO_FACTOR * recent peak echo level).
BARGE_IN_MIN_RMS = float(os.environ.get("BARGE_IN_MIN_RMS", "600"))
BARGE_IN_ECHO_FACTOR = 1.5
ECHO_PEAK_DECAY = 0.997      # per chunk (~64 ms): the echo peak estimate halves in ~15 s
BARGE_IN_CHUNKS = 3          # consecutive loud chunks needed (~0.2 s) to avoid triggering on clicks
PREROLL_CHUNKS = 8           # ~0.5 s of muted mic audio sent on barge-in so Vikki hears the whole phrase
PLAYBACK_PIECE_BYTES = int(RECEIVE_SAMPLE_RATE * 2 * 0.05)  # write 50 ms at a time so playback stops quickly

MODEL = os.environ.get("VIKKI_MODEL", "models/gemini-3.8-live")
ASSISTANT_NAME = "Vikki"

SYSTEM_INSTRUCTION = f"""\
Your name is {ASSISTANT_NAME}. You are a friendly, helpful live vision and voice assistant
that can see the user through their camera and talk with them in real time.

- Whenever someone asks your name (e.g. "what's your name?", "who are you?"), answer that
  your name is {ASSISTANT_NAME}.
- When someone addresses you by name (e.g. "Hi {ASSISTANT_NAME}", "Hey {ASSISTANT_NAME}"),
  greet them back warmly and continue the conversation.
- Always refer to yourself as {ASSISTANT_NAME}, the Vikki Vision assistant. Never mention the
  underlying AI model, the company that makes it, or the technology you are built on. If asked,
  simply say you are {ASSISTANT_NAME} from Vikki Vision.
"""

CONFIG = types.LiveConnectConfig(
    system_instruction=SYSTEM_INSTRUCTION,
    response_modalities=["AUDIO"],
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
    media_resolution="MEDIA_RESOLUTION_MEDIUM",
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Zephyr")
        )
    ),
    context_window_compression=types.ContextWindowCompressionConfig(
        trigger_tokens=104857,
        sliding_window=types.SlidingWindow(target_tokens=52428),
    ),
)


def _rms(pcm: bytes) -> float:
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0


def create_client() -> genai.Client:
    api_key = os.environ.get("VIKKI_API_KEY")
    if not api_key or api_key == "your-api-key-here":
        raise RuntimeError("VIKKI_API_KEY is not set. Add it to the .env file (see .env.example).")
    return genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)


class LiveSession:
    def __init__(self, client: genai.Client):
        self.client = client

        self.session = None
        self.audio_in_queue: asyncio.Queue | None = None
        self.out_queue: asyncio.Queue | None = None

        self.mic_stream = None
        self.speaker_stream = None
        self.capture = None
        self.recorder: SessionRecorder | None = None
        self.last_playback_time = 0.0
        self.user_turn_ended = False
        self.playback_epoch = 0      # bumped on every interruption; playback stops mid-chunk when it changes
        self.echo_peak = 0.0

    # ---------- outgoing ----------

    def _encode_jpeg(self, img: "PIL.Image.Image") -> types.Blob:
        img.thumbnail((1024, 1024))
        buf = io.BytesIO()
        img.save(buf, format="jpeg")
        return types.Blob(data=buf.getvalue(), mime_type="image/jpeg")

    def _get_frame(self):
        try:
            ret, frame = self.capture.read()
            if not ret:
                return None
            # OpenCV captures in BGR but PIL expects RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            blob = self._encode_jpeg(PIL.Image.fromarray(frame_rgb))
            if self.recorder is not None:
                self.recorder.save_frame(blob.data)
            return blob
        except Exception:
            log.exception("Failed to read camera frame")
            return None

    async def get_frames(self):
        try:
            # Opening the camera takes about a second; keep it off the event loop
            self.capture = await asyncio.to_thread(cv2.VideoCapture, 0)
            if not self.capture.isOpened():
                raise RuntimeError("Could not open the default camera (index 0)")
            log.info("Camera opened")

            frames_sent = 0
            while True:
                frame = await asyncio.to_thread(self._get_frame)
                if frame is None:
                    log.warning("Camera returned no frame, stopping video stream")
                    break
                await self.out_queue.put({"video": frame})
                frames_sent += 1
                if frames_sent % 30 == 0:
                    log.debug("Queued %d camera frames", frames_sent)
                await asyncio.sleep(FRAME_INTERVAL_SECONDS)
        except Exception:
            log.exception("Camera streaming failed")
            raise
        finally:
            if self.capture is not None:
                self.capture.release()
                log.info("Camera released")

    async def listen_audio(self):
        try:
            self.mic_stream = sd.RawInputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
            )
            self.mic_stream.start()
            log.info("Microphone opened: %s", sd.query_devices(kind="input")["name"])

            preroll = collections.deque(maxlen=PREROLL_CHUNKS)
            loud_chunks = 0
            muted_levels = []
            open_mic_peak = 0.0
            while True:
                data, overflowed = await asyncio.to_thread(self.mic_stream.read, CHUNK_SIZE)
                if overflowed:
                    log.debug("Microphone input overflow")
                blob = types.Blob(data=bytes(data), mime_type=f"audio/pcm;rate={SEND_SAMPLE_RATE}")

                level = _rms(data)
                if not self._vikki_is_speaking():
                    open_mic_peak = max(open_mic_peak, level)
                    if muted_levels:
                        log.debug(
                            "Mic level while Vikki spoke: median=%.0f max=%.0f (barge-in threshold %.0f)",
                            float(np.median(muted_levels)), max(muted_levels), self._barge_in_threshold(),
                        )
                        muted_levels = []
                    if self.user_turn_ended:
                        log.debug("Mic peak level while the user had the floor: %.0f", open_mic_peak)
                        open_mic_peak = 0.0
                        self.user_turn_ended = False
                    preroll.clear()
                    loud_chunks = 0
                    await self.out_queue.put({"audio": blob})
                    continue

                # Vikki is speaking: don't send her own echo back to her, but watch for the user talking over her
                preroll.append(blob)
                muted_levels.append(level)
                if level > self._barge_in_threshold():
                    loud_chunks += 1
                else:
                    loud_chunks = 0
                    self.echo_peak = max(level, self.echo_peak * ECHO_PEAK_DECAY)

                if loud_chunks >= BARGE_IN_CHUNKS:
                    log.info("User started talking over Vikki (mic level %.0f) - interrupting", level)
                    self._stop_playback()
                    while preroll:
                        await self.out_queue.put({"audio": preroll.popleft()})
                    loud_chunks = 0
        except Exception:
            log.exception("Microphone streaming failed")
            raise

    def _barge_in_threshold(self) -> float:
        return max(BARGE_IN_MIN_RMS, BARGE_IN_ECHO_FACTOR * self.echo_peak)

    def _stop_playback(self) -> int:
        """Silence Vikki now: drop queued audio and unmute the mic. Returns chunks dropped."""
        self.playback_epoch += 1
        dropped = 0
        while not self.audio_in_queue.empty():
            self.audio_in_queue.get_nowait()
            dropped += 1
        self.last_playback_time = 0.0
        return dropped

    def _vikki_is_speaking(self) -> bool:
        if self.audio_in_queue is not None and not self.audio_in_queue.empty():
            return True
        return time.monotonic() - self.last_playback_time < MIC_UNMUTE_DELAY_SECONDS

    async def send_realtime(self):
        try:
            while True:
                msg = await self.out_queue.get()
                await self.session.send_realtime_input(**msg)
        except Exception:
            log.exception("Failed to send realtime input")
            raise

    # ---------- incoming ----------

    async def receive_audio(self):
        """Read from the websocket and push PCM chunks to the playback queue."""
        try:
            while True:
                user_said, vikki_said = [], []
                user_started = vikki_started = None
                turn_epoch = None
                async for response in self.session.receive():
                    if turn_epoch is None:
                        turn_epoch = self.playback_epoch
                    # After a local barge-in, discard the rest of the interrupted reply
                    if (data := response.data) and self.playback_epoch == turn_epoch:
                        self.audio_in_queue.put_nowait(data)

                    server_content = response.server_content
                    if server_content is None:
                        continue
                    if server_content.input_transcription and server_content.input_transcription.text:
                        user_said.append(server_content.input_transcription.text)
                        user_started = user_started or datetime.now()
                    if server_content.output_transcription and server_content.output_transcription.text:
                        vikki_said.append(server_content.output_transcription.text)
                        vikki_started = vikki_started or datetime.now()
                    if server_content.interrupted:
                        dropped = self._stop_playback()
                        log.info("Vikki was interrupted (dropped %d queued audio chunks)", dropped)

                if user_said:
                    text = "".join(user_said).strip()
                    log.info("User said: %s", text)
                    self.recorder.add_message("User", text, user_started)
                    self.user_turn_ended = True
                if vikki_said:
                    text = "".join(vikki_said).strip()
                    log.info("%s said: %s", ASSISTANT_NAME, text)
                    self.recorder.add_message(ASSISTANT_NAME, text, vikki_started)
                log.debug("Turn complete")
        except Exception:
            log.exception("Receiving responses failed")
            raise

    async def play_audio(self):
        try:
            self.speaker_stream = sd.RawOutputStream(
                samplerate=RECEIVE_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
            )
            self.speaker_stream.start()
            log.info("Speaker opened: %s", sd.query_devices(kind="output")["name"])

            while True:
                chunk = await self.audio_in_queue.get()
                epoch = self.playback_epoch
                for start in range(0, len(chunk), PLAYBACK_PIECE_BYTES):
                    if self.playback_epoch != epoch:
                        break  # interrupted mid-chunk
                    self.last_playback_time = time.monotonic()
                    await asyncio.to_thread(self.speaker_stream.write, chunk[start:start + PLAYBACK_PIECE_BYTES])
                    if self.playback_epoch == epoch:
                        self.last_playback_time = time.monotonic()
        except Exception:
            log.exception("Audio playback failed")
            raise

    # ---------- lifecycle ----------

    def _close_audio(self):
        for name, stream in (("microphone", self.mic_stream), ("speaker", self.speaker_stream)):
            try:
                if stream is not None:
                    stream.stop()
                    stream.close()
                    log.info("Closed %s stream", name)
            except Exception:
                log.exception("Error closing %s stream", name)

    async def run(self):
        log.info("Connecting to %s...", ASSISTANT_NAME)
        try:
            async with (
                self.client.aio.live.connect(model=MODEL, config=CONFIG) as session,
                asyncio.TaskGroup() as tg,
            ):
                self.session = session
                log.info("Connected - %s is live", ASSISTANT_NAME)
                self.recorder = SessionRecorder()

                self.audio_in_queue = asyncio.Queue()
                self.out_queue = asyncio.Queue(maxsize=5)

                tg.create_task(self.send_realtime())
                tg.create_task(self.listen_audio())
                tg.create_task(self.get_frames())
                tg.create_task(self.receive_audio())
                tg.create_task(self.play_audio())
                log.info("Streaming camera and microphone - press Ctrl+C to quit")

        except asyncio.CancelledError:
            log.info("Session cancelled")
        except ExceptionGroup as eg:
            for exc in eg.exceptions:
                log.error("Task failed: %r", exc, exc_info=exc)
        except Exception:
            log.exception("Live session failed")
        finally:
            self._close_audio()
            if self.recorder is not None:
                self.recorder.close()
            log.info("Session ended")


def main():
    try:
        client = create_client()
        asyncio.run(LiveSession(client).run())
    except KeyboardInterrupt:
        log.info("Interrupted with Ctrl+C")
    except Exception:
        log.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
