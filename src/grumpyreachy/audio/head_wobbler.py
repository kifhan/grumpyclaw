"""Speech-reactive head wobble: secondary motion offset from audio energy."""

from __future__ import annotations

import math
import struct
from typing import Callable

# Default: small wobble amplitude in world coords
DEFAULT_AMPLITUDE = 0.02
DEFAULT_DECAY = 0.92


class HeadWobbler:
    """
    Consumes raw audio chunks (e.g. 24kHz PCM int16), computes energy,
    and calls an offset callback (dx, dy, dz) for the movement manager.
    """

    def __init__(
        self,
        on_offset: Callable[[float, float, float], None],
        amplitude: float = DEFAULT_AMPLITUDE,
        decay: float = DEFAULT_DECAY,
    ):
        self._on_offset = on_offset
        self._amplitude = amplitude
        self._decay = decay
        self._energy: float = 0.0

    def push_audio(self, pcm_chunk: bytes) -> None:
        """Update energy from PCM chunk and apply wobble offset."""
        if len(pcm_chunk) < 2:
            return
        # RMS over chunk (int16 little-endian)
        step = 2
        total = 0.0
        n = 0
        for i in range(0, len(pcm_chunk) - 1, step):
            sample = struct.unpack_from("<h", pcm_chunk, i)[0]
            total += sample * sample
            n += 1
        if n == 0:
            return
        rms = math.sqrt(total / n) / 32768.0
        self._energy = self._energy * self._decay + rms * (1.0 - self._decay)
        # Wobble in z (nod) and slight y (shake)
        dz = self._amplitude * math.sin(self._energy * 20) * self._energy
        dy = self._amplitude * 0.3 * math.cos(self._energy * 17) * self._energy
        self._on_offset(0.0, dy, dz)
