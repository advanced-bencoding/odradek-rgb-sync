"""Print (and optionally log) every animation state change live, with typed markers."""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from ..game import StateReader
from ..util import stamp


def _stdin_lines(q: queue.Queue) -> None:
    for line in sys.stdin:
        q.put(line.rstrip("\n"))


def watch(reader: StateReader, hz: float = 30, log_path: Path | None = None, ignore: Callable[[str], bool] = lambda n: False,
          should_stop: Callable[[], bool] = lambda: False, markers: bool = True) -> None:
    """Runs until should_stop() or Ctrl+C. Lines typed on stdin become MARK lines in the output and log."""
    log = open(log_path, "a", encoding="utf-8") if log_path else None
    q: queue.Queue = queue.Queue()
    if markers and sys.stdin and sys.stdin.isatty():
        threading.Thread(target=_stdin_lines, args=(q,), daemon=True).start()
        print("# type a note and press Enter to drop a marker", flush=True)
    prev: dict[str, int] = {}
    try:
        while not should_stop():
            now = time.time()
            while not q.empty():
                note = q.get()
                print(f"{stamp(now)}  ===== MARK: {note}", flush=True)
                if log:
                    log.write(json.dumps({"t": round(now, 3), "mark": note}) + "\n")
            states = reader.read()
            if states is None:
                print(f"{stamp(now)}  # memory unreadable (game closed?)", flush=True)
                return
            changes = {k: (prev.get(k), v) for k, v in states.items() if prev.get(k) != v and not ignore(k)}
            if changes:
                first = not prev
                text = "  ".join(f"{k} {v}" if first else f"{k} {a}->{v}" for k, (a, v) in changes.items()
                                 if not first or v != 2)
                if text:
                    print(f"{stamp(now)}  {'initial: ' if first else ''}{text}", flush=True)
                if log:
                    for k, (a, v) in changes.items():
                        log.write(json.dumps({"t": round(now, 3), "anim": k, "from": a, "to": v}) + "\n")
                    log.flush()
            prev = states
            time.sleep(max(0.0, 1 / hz - (time.time() - now)))
    finally:
        if log:
            log.close()
