"""Microphone input as 16 kHz mono 16-bit PCM chunks."""

import asyncio

import sounddevice as sd

from vikki_vision.utils.logger import get_logger

log = get_logger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_FRAMES = 1024  # ~64 ms per chunk
MIME_TYPE = f"audio/pcm;rate={SAMPLE_RATE}"


class Microphone:
    def __init__(self, sample_rate: int = SAMPLE_RATE, chunk_frames: int = CHUNK_FRAMES):
        self.sample_rate = sample_rate
        self.chunk_frames = chunk_frames
        self._stream: sd.RawInputStream | None = None

    def open(self) -> None:
        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype="int16",
            blocksize=self.chunk_frames,
        )
        self._stream.start()
        log.info("Microphone opened: %s", sd.query_devices(kind="input")["name"])

    async def read(self) -> bytes:
        """Read the next chunk without blocking the event loop."""
        data, overflowed = await asyncio.to_thread(self._stream.read, self.chunk_frames)
        if overflowed:
            log.debug("Microphone input overflow")
        return bytes(data)

    def close(self) -> None:
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
                log.info("Microphone closed")
        except Exception:
            log.exception("Error closing microphone")
