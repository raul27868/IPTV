"""Unit tests for bounded recovery and interruption durations (no Cast hardware)."""
import unittest

from cast_recovery import CastRecoveryTracker, MAX_FULL_RESTARTS


class RecoveryTests(unittest.TestCase):
    def test_natural_recovery_duration(self):
        t = CastRecoveryTracker()
        self.assertEqual(t.observe("receiver_stalled", now=100), "none")
        self.assertEqual(t.observe("healthy", now=109), "recovered")
        self.assertEqual(t.last_event.duration, 9)
        self.assertEqual(t.last_event.recovery, "natural")

    def test_receiver_then_full_restart(self):
        t = CastRecoveryTracker()
        t.observe("receiver_stalled", now=100)
        self.assertEqual(t.observe("receiver_stalled", now=116), "reload")
        self.assertEqual(t.observe("receiver_stalled", now=120), "none")
        t.action_complete(True, now=120)
        self.assertEqual(t.observe("receiver_stalled", now=141), "restart")
        self.assertEqual(t.observe("receiver_stalled", now=142), "none")
        t.action_complete(True, now=143)
        self.assertEqual(t.observe("healthy", now=149), "recovered")
        self.assertEqual(t.last_event.duration, 49)
        self.assertEqual(t.last_event.recovery, "full")

    def test_source_never_tries_receiver_only(self):
        t = CastRecoveryTracker()
        t.observe("source_stalled", now=100)
        self.assertEqual(t.observe("source_stalled", now=119), "none")
        self.assertEqual(t.observe("source_stalled", now=120), "restart")

    def test_full_restart_limit_in_window(self):
        t = CastRecoveryTracker()
        t.observe("source_stalled", now=100)
        for n in range(MAX_FULL_RESTARTS):
            start = 125 + n * 35
            self.assertEqual(t.observe("source_stalled", now=start), "restart")
            t.action_complete(False, now=start + 1)
        self.assertEqual(t.observe("source_stalled", now=210), "exhausted")
        self.assertEqual(t.observe("source_stalled", now=800), "restart")

    def test_auto_disabled(self):
        t = CastRecoveryTracker(automatic=False)
        t.observe("source_stalled", now=100)
        self.assertEqual(t.observe("source_stalled", now=999), "none")
        self.assertEqual(t.observe("healthy", now=1000), "recovered")

    def test_initializing_does_not_close_problem(self):
        t = CastRecoveryTracker()
        t.observe("receiver_stalled", now=10)
        self.assertEqual(t.observe("initializing", now=22), "none")
        self.assertIsNotNone(t.problem_since)

    def test_no_private_data_in_events(self):
        t = CastRecoveryTracker()
        t.observe("source_stalled", now=10)
        t.observe("healthy", now=15)
        self.assertEqual(t.events[0].cause, "source_stalled")


if __name__ == "__main__":
    unittest.main()
