"""Recon mode: tools for mapping new animations (and new game builds) to signals.

Typical workflow for a new Odradek behaviour (see CONTRIBUTING.md):
  1. `recon watch --log ...` while you play; type a note + Enter when it happens (a marker).
  2. Read which animations started/stopped around the marker.
  3. Optionally confirm with `recon capture <label>` in each state, then `recon compare`.
  4. Add the animation(s) to config/signals/<game>.toml and an effect rule to config/effects/*.toml.

For a game build where the vtable moved, `recon discover` finds the object layout again.
"""
from .capture import CaptureStore
from .discover import discover_layout
from .watch import watch

__all__ = ["CaptureStore", "discover_layout", "watch"]
