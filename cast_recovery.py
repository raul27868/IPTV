"""State tracking and bounded recovery decisions for legacy Google Cast.

The tracker is per-playback-session; it records interruption duration and
whether service returned naturally, after receiver reload, or full restart.
It never contains IPTV URLs or credentials.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import time

LOG = logging.getLogger("iptv-video")
PROBLEM_KINDS = frozenset({"source_stopped", "source_stalled", "receiver_stalled", "receiver_idle", "receiver_buffering"})
SOURCE_KINDS = frozenset({"source_stopped", "source_stalled"})
RECEIVER_KINDS = frozenset({"receiver_stalled", "receiver_idle", "receiver_buffering"})
MAX_RECEIVER_RELOADS = 1
MAX_FULL_RESTARTS = 2
RESTART_WINDOW = 600.0
RECOVERY_COOLDOWN = 20.0


@dataclass(frozen=True)
class Interruption:
    cause: str
    duration: float
    recovery: str


class CastRecoveryTracker:
    def __init__(self, *, automatic: bool = True):
        self.automatic = automatic
        self.problem_since: float | None = None
        self.cause = ""
        self.pending_action: str | None = None
        self.receiver_reloads = 0
        self.full_restarts = deque()
        self.retry_not_before = 0.0
        self.events: list[Interruption] = []
        self.session_recovery = "natural"
        self.last_event: Interruption | None = None

    def observe(self, kind: str, *, now: float | None = None) -> str:
        """Observe health and recommend 'reload', 'restart' or 'none'.

        The *caller* performs asynchronous I/O after receiving the decision.
        Request recovery only after a sustained error, with cooldown and
        bounded attempts. An in-progress operation never triggers a duplicate.
        """
        now = time.monotonic() if now is None else now
        if kind not in PROBLEM_KINDS:
            if self.problem_since is not None and kind == "healthy":
                duration = max(0.0, now - self.problem_since)
                event = Interruption(self.cause, duration, self.session_recovery)
                self.events.append(event)
                self.last_event = event
                LOG.info("Cast interrupción resuelta causa=%s duración=%.1fs recuperación=%s",
                         event.cause, event.duration, event.recovery)
                self.problem_since = None
                self.cause = ""
                self.receiver_reloads = 0
                self.pending_action = None
                self.session_recovery = "natural"
                return "recovered"
            return "none"
        if self.problem_since is None:
            self.problem_since = now
            self.cause = kind
            self.receiver_reloads = 0
            self.session_recovery = "natural"
            LOG.warning("Cast interrupción detectada tipo=%s", kind)
        elif kind in SOURCE_KINDS and self.cause not in SOURCE_KINDS:
            self.cause = kind

        if not self.automatic or self.pending_action is not None or now < self.retry_not_before:
            return "none"
        elapsed = now - self.problem_since
        if kind in RECEIVER_KINDS and elapsed >= 15 and self.receiver_reloads < MAX_RECEIVER_RELOADS:
            self.receiver_reloads += 1
            self.pending_action = "reload"
            self.session_recovery = "receiver"
            return "reload"
        if kind in SOURCE_KINDS and elapsed >= 20:
            return self._request_full_restart(now)
        if kind in RECEIVER_KINDS and elapsed >= 35 and self.receiver_reloads:
            return self._request_full_restart(now)
        return "none"

    def _request_full_restart(self, now: float) -> str:
        while self.full_restarts and now - self.full_restarts[0] > RESTART_WINDOW:
            self.full_restarts.popleft()
        if len(self.full_restarts) >= MAX_FULL_RESTARTS:
            return "exhausted"
        self.full_restarts.append(now)
        self.pending_action = "restart"
        self.session_recovery = "full"
        return "restart"

    def action_complete(self, success: bool, *, now: float | None = None):
        now = time.monotonic() if now is None else now
        self.pending_action = None
        self.retry_not_before = now + RECOVERY_COOLDOWN
        if not success:
            LOG.warning("Cast recuperación fallida; siguiente intento condicionado por cooldown")

    def finish(self, *, now: float | None = None, reason: str = "stopped"):
        """Record a still-open interruption when playback is manually stopped."""
        if self.problem_since is None:
            return
        now = time.monotonic() if now is None else now
        event = Interruption(self.cause, max(0.0, now - self.problem_since), reason)
        self.events.append(event)
        self.last_event = event
        LOG.info("Cast interrupción cerrada causa=%s duración=%.1fs resultado=%s",
                 event.cause, event.duration, reason)
        self.problem_since = None
        self.pending_action = None

    def handoff_full_restart(self):
        """Transfer interruption history/counters to a newly created Cast session."""
        self.pending_action = "restart"
        return self

    def describe(self, *, now: float | None = None) -> str:
        if self.problem_since is None:
            if self.last_event:
                e = self.last_event
                return f"Último corte: {e.duration:.0f} s; recuperación {e.recovery}."
            return "Sin cortes detectados."
        now = time.monotonic() if now is None else now
        return f"Interrupción actual: {max(0.0, now-self.problem_since):.0f} s; tipo {self.cause}."
