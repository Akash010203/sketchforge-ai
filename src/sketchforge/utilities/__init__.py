"""Small, self-contained helpers shared across SketchForge modules.

Submodules
----------
hashing    — stable content hashing (SHA-256, canonical JSON)
memory     — in-process RAM/VRAM inspection and budget guards
paths      — repository root discovery, safe joins, atomic writes
timing     — wall-clock Stopwatch for performance tracking
validation — generic schema and bounds validation helpers
"""

from sketchforge.utilities import hashing, memory, paths, timing, validation

__all__ = ["hashing", "memory", "paths", "timing", "validation"]
