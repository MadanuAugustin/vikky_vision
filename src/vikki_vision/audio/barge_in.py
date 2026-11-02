"""
Barge-in detection: lets the user interrupt Vikki by talking over her.

While Vikki speaks, her voice leaks from the speakers back into the microphone (echo).
A mic chunk counts as the user speaking when its level exceeds
max(min_rms, echo_factor * recent peak echo level) for `trigger_chunks` chunks in a row.
"""

import numpy as np


def rms(pcm: bytes) -> float:
    """Root-mean-square level of 16-bit PCM audio."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0


class BargeInDetector:
    def __init__(
        self,
        min_rms: float = 600.0,
        echo_factor: float = 1.5,
        echo_decay: float = 0.997,   # per ~64 ms chunk: the echo peak estimate halves in ~15 s
        trigger_chunks: int = 3,     # ~0.2 s of loud audio, so clicks and bumps don't trigger it
    ):
        self.min_rms = min_rms
        self.echo_factor = echo_factor
        self.echo_decay = echo_decay
        self.trigger_chunks = trigger_chunks
        self.echo_peak = 0.0
        self._loud_chunks = 0

    @property
    def threshold(self) -> float:
        return max(self.min_rms, self.echo_factor * self.echo_peak)

    def reset(self) -> None:
        """Forget any partial detection (call when Vikki stops speaking)."""
        self._loud_chunks = 0

    def update(self, level: float) -> bool:
        """Feed the level of one mic chunk captured while Vikki speaks. True = user barged in."""
        if level > self.threshold:
            self._loud_chunks += 1
        else:
            self._loud_chunks = 0
            self.echo_peak = max(level, self.echo_peak * self.echo_decay)

        if self._loud_chunks >= self.trigger_chunks:
            self._loud_chunks = 0
            return True
        return False
