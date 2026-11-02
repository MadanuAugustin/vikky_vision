"""
Vikki Vision - live camera / screen + voice streaming with the Gemini Live API.

Based on Google's official google-genai Live API sample (see ai_studio_code.py),
adapted to:
  * use `sounddevice` instead of PyAudio (PyAudio has no prebuilt wheels for newer Pythons)
  * use the current `send_realtime_input` SDK methods instead of the deprecated `send`
  * log every event via logger.py and wrap all work in try/except

Usage:
    python liveAPI.py --mode camera   # webcam + mic (default)
    python liveAPI.py --mode screen   # screen capture + mic
    python liveAPI.py --mode none     # mic / text only

Type a message and press Enter to send text; type 'q' to quit.
"""

import argparse
import asyncio
import io
import os
import sys

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

MODEL = os.environ.get("GEMINI_MODEL", "models/gemini-3.8-live")
DEFAULT_MODE = "camera"

CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
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
    def __init__(self, client: genai.Client, video_mode: str = DEFAULT_MODE):
        self.client = client
        self.video_mode = video_mode

        self.session = None
        self.audio_in_queue: asyncio.Queue | None = None
        self.out_queue: asyncio.Queue | None = None

        self.mic_stream = None
        self.speaker_stream = None
        self.capture = None

    # ---------- outgoing ----------

    async def send_text(self):
        try:
            while True:
                text = await asyncio.to_thread(input, "message > ")
                if text.strip().lower() == "q":
                    log.info("User requested exit")
                    break
                if self.session is not None:
                    await self.session.send_realtime_input(text=text or ".")
                    log.info("Sent text message (%d chars)", len(text))
        except EOFError:
            log.info("Input closed, exiting")
        except Exception:
            log.exception("send_text failed")
            raise

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

    def _get_screen(self):
        try:
            import mss
            import mss.tools

            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[0])
                png_bytes = mss.tools.to_png(shot.rgb, shot.size)
            img = PIL.Image.open(io.BytesIO(png_bytes)).convert("RGB")
            return self._encode_jpeg(img)
        except Exception:
            log.exception("Failed to capture screen")
            return None

    async def get_screen(self):
        try:
            log.info("Screen capture started")
            while True:
                frame = await asyncio.to_thread(self._get_screen)
                if frame is None:
                    break
                await self.out_queue.put({"video": frame})
                await asyncio.sleep(FRAME_INTERVAL_SECONDS)
        except Exception:
            log.exception("Screen streaming failed")
            raise

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
                blob = types.Blob(data=bytes(data), mime_type=f"audio/pcm;rate={SEND_SAMPLE_RATE}")
                await self.out_queue.put({"audio": blob})
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

    async def receive_audio(self):
        """Read from the websocket and push PCM chunks to the playback queue."""
        try:
            while True:
                async for response in self.session.receive():
                    if data := response.data:
                        self.audio_in_queue.put_nowait(data)
                        continue
                    if text := response.text:
                        print(text, end="", flush=True)

                    server_content = response.server_content
                    if server_content is not None and server_content.interrupted:
                        log.info("Model was interrupted by the user")

                # The turn is complete (or interrupted): drop any audio not yet
                # played so an interruption stops playback immediately.
                dropped = 0
                while not self.audio_in_queue.empty():
                    self.audio_in_queue.get_nowait()
                    dropped += 1
                log.debug("Turn complete (dropped %d queued audio chunks)", dropped)
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
                await asyncio.to_thread(self.speaker_stream.write, chunk)
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
        log.info("Connecting to %s (mode=%s)", MODEL, self.video_mode)
        try:
            async with (
                self.client.aio.live.connect(model=MODEL, config=CONFIG) as session,
                asyncio.TaskGroup() as tg,
            ):
                self.session = session
                log.info("Connected to Gemini Live session")

                self.audio_in_queue = asyncio.Queue()
                self.out_queue = asyncio.Queue(maxsize=5)

                send_text_task = tg.create_task(self.send_text())
                tg.create_task(self.send_realtime())
                tg.create_task(self.listen_audio())
                if self.video_mode == "camera":
                    tg.create_task(self.get_frames())
                elif self.video_mode == "screen":
                    tg.create_task(self.get_screen())
                tg.create_task(self.receive_audio())
                tg.create_task(self.play_audio())

                await send_text_task
                raise asyncio.CancelledError("User requested exit")

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
    parser = argparse.ArgumentParser(description="Vikki Vision - Gemini Live camera/screen streaming")
    parser.add_argument(
        "--mode",
        type=str,
        default=DEFAULT_MODE,
        choices=["camera", "screen", "none"],
        help="pixels to stream from",
    )
    args = parser.parse_args()

    try:
        client = create_client()
        asyncio.run(LiveSession(client, video_mode=args.mode).run())
    except KeyboardInterrupt:
        log.info("Interrupted with Ctrl+C")
    except Exception:
        log.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
