"""The main loop: game memory -> animation states -> signals -> outputs, at a fixed rate."""
from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from .game import Attach, GameSession
from .outputs import Output
from .signals import SignalPipeline

RETRY = {Attach.NO_PROCESS: 2.0, Attach.NOT_LOADED: 15.0, Attach.DENIED: 30.0}


class SyncEngine:
    def __init__(self, session: GameSession, pipeline: SignalPipeline, outputs: Sequence[Output],
                 fps: float = 30, log: Callable[[str], None] = print,
                 on_status: Callable[[Attach | str], None] = lambda s: None):
        """on_status gets each new Attach status, plus "closed" (game exited) or "reloading"
        (animation objects moved, e.g. a save was loaded) when an attached game is lost."""
        self.session, self.pipeline, self.outputs = session, pipeline, list(outputs)
        self.fps, self.log, self.on_status = fps, log, on_status

    def run(self, should_stop: Callable[[], bool] = lambda: False) -> None:
        next_attach, last_status, signals = 0.0, None, SignalPipeline.idle()
        try:
            while not should_stop():
                now = time.time()
                states = None
                if self.session.attached:
                    states = self.session.read()
                    if not self.session.attached:
                        next_attach = now  # game closed or objects moved: try again straight away
                        last_status = None
                        # detach() clears memory when the game closed; objects moving keeps it
                        self.on_status("closed" if self.session.memory is None else "reloading")
                if not self.session.attached and now >= next_attach:
                    status = self.session.try_attach()
                    if status != last_status:
                        self.log(status.value)
                        self.on_status(status)
                        last_status = status
                    if status != Attach.ATTACHED:
                        next_attach = time.time() + RETRY[status]
                    else:
                        states = self.session.read()
                    now = time.time()
                if self.session.attached:
                    if states is not None:
                        signals = self.pipeline.evaluate(now, states)
                else:
                    signals = SignalPipeline.idle()
                for o in self.outputs:
                    o.update(now, signals, states)
                time.sleep(max(0.0, 1 / self.fps - (time.time() - now)))
        finally:
            for o in self.outputs:
                o.close()
            self.session.detach()
