"""
Vikki Vision - live camera + voice streaming with the Gemini Live API.

Streams the default webcam and microphone to Gemini and plays Vikki's spoken replies,
so the whole conversation happens by voice while the model watches the camera.

Based on Google's official google-genai Live API sample, adapted to:
  * use `sounddevice` instead of PyAudio (PyAudio has no prebuilt wheels for newer Pythons)
  * use the current `send_realtime_input` SDK method instead of the deprecated `send`
  * mute the microphone while Vikki is speaking so she doesn't hear herself through the speakers
  * log every event via logger.py and wrap all work in try/except

Usage:
    python liveAPI.py

Press Ctrl+C to quit.
"""

import asyncio
import io
import os
import sys
import time

from logger import get_logger

log = get_logger("liveAPI")

try:
    import cv2
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

MODEL = os.environ.get("GEMINI_MODEL", "models/gemini-3.8-live")
ASSISTANT_NAME = "Vikki"

SYSTEM_INSTRUCTION = f"""\
Your name is {ASSISTANT_NAME}. You are a friendly, helpful live vision and voice assistant
that can see the user through their camera and talk with them in real time.

- Whenever someone asks your name (e.g. "what's your name?", "who are you?"), answer that
  your name is {ASSISTANT_NAME}.
- When someone addresses you by name (e.g. "Hi {ASSISTANT_NAME}", "Hey {ASSISTANT_NAME}"),
  greet them back warmly and continue the conversation.
- Always refer to yourself as {ASSISTANT_NAME}. Do not call yourself Gemini or say you are
  a Google model unless the user specifically asks what technology you are built on.
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


def create_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key == "your-gemini-api-key-here":
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to the .env file (see .env.example).")
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
        self.last_playback_time = 0.0

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
            return self._encode_jpeg(PIL.Image.fromarray(frame_rgb))
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

            while True:
                data, overflowed = await asyncio.to_thread(self.mic_stream.read, CHUNK_SIZE)
                if overflowed:
                    log.debug("Microphone input overflow")
                if self._vikki_is_speaking():
                    continue
                blob = types.Blob(data=bytes(data), mime_type=f"audio/pcm;rate={SEND_SAMPLE_RATE}")
                await self.out_queue.put({"audio": blob})
        except Exception:
            log.exception("Microphone streaming failed")
            raise

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
                async for response in self.session.receive():
                    if data := response.data:
                        self.audio_in_queue.put_nowait(data)

                    server_content = response.server_content
                    if server_content is None:
                        continue
                    if server_content.input_transcription and server_content.input_transcription.text:
                        user_said.append(server_content.input_transcription.text)
                    if server_content.output_transcription and server_content.output_transcription.text:
                        vikki_said.append(server_content.output_transcription.text)
                    if server_content.interrupted:
                        # Stop playback immediately by dropping audio that hasn't played yet
                        dropped = 0
                        while not self.audio_in_queue.empty():
                            self.audio_in_queue.get_nowait()
                            dropped += 1
                        log.info("Vikki was interrupted (dropped %d queued audio chunks)", dropped)

                if user_said:
                    log.info("User said: %s", "".join(user_said).strip())
                if vikki_said:
                    log.info("%s said: %s", ASSISTANT_NAME, "".join(vikki_said).strip())
                log.debug("Turn complete")
        except Exception:
            log.exception("Receiving from Gemini failed")
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
                self.last_playback_time = time.monotonic()
                await asyncio.to_thread(self.speaker_stream.write, chunk)
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
        log.info("Connecting to %s", MODEL)
        try:
            async with (
                self.client.aio.live.connect(model=MODEL, config=CONFIG) as session,
                asyncio.TaskGroup() as tg,
            ):
                self.session = session
                log.info("Connected to Gemini Live session")

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
