"""Plays Vikki's voice (24 kHz mono 16-bit PCM) and supports stopping it instantly."""

import asyncio
import time

import sounddevice as sd

from vikki_vision.utils.logger import get_logger

log = get_logger(__name__)

SAMPLE_RATE = 24000
CHANNELS = 1
PIECE_BYTES = int(SAMPLE_RATE * 2 * 0.05)  # write 50 ms at a time so playback stops quickly
# Consider Vikki still speaking this long after the last audio, to cover speaker latency/room echo
UNMUTE_DELAY_SECONDS = 0.6


class Speaker:
    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        # Bumped on every interruption; playback in progress stops when it changes
        self.epoch = 0
        self._last_playback_time = 0.0
        self._stream: sd.RawOutputStream | None = None

    def open(self) -> None:
        self._stream = sd.RawOutputStream(samplerate=self.sample_rate, channels=CHANNELS, dtype="int16")
        self._stream.start()
        log.info("Speaker opened: %s", sd.query_devices(kind="output")["name"])

    def enqueue(self, chunk: bytes) -> None:
        self.queue.put_nowait(chunk)

    def is_speaking(self) -> bool:
        if not self.queue.empty():
            return True
        return time.monotonic() - self._last_playback_time < UNMUTE_DELAY_SECONDS

    def stop(self) -> int:
        """Silence Vikki immediately. Returns the number of queued chunks dropped."""
        self.epoch += 1
        dropped = 0
        while not self.queue.empty():
            self.queue.get_nowait()
            dropped += 1
        self._last_playback_time = 0.0
        return dropped

    async def run(self) -> None:
        """Play queued audio until cancelled."""
        while True:
            chunk = await self.queue.get()
            epoch = self.epoch
            for start in range(0, len(chunk), PIECE_BYTES):
                if self.epoch != epoch:
                    break  # interrupted mid-chunk
                self._last_playback_time = time.monotonic()
                await asyncio.to_thread(self._stream.write, chunk[start:start + PIECE_BYTES])
                if self.epoch == epoch:
                    self._last_playback_time = time.monotonic()

    def close(self) -> None:
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
                log.info("Speaker closed")
        except Exception:
            log.exception("Error closing speaker")
