import subprocess
import threading
import time
import unittest
from unittest.mock import Mock, call, patch

import numpy as np

from adb_controller import ADBController, ContinuousCapture, NO_WINDOW


class ContinuousCaptureTests(unittest.TestCase):
    def test_latest_frame_replaces_backlog_and_is_immutable(self):
        controller = Mock()
        controller.screenshot.side_effect = lambda timeout: np.zeros((10, 10, 3), np.uint8)
        with ContinuousCapture(controller, max_fps=100) as capture:
            first = capture.next_frame()
            time.sleep(.06)
            latest = capture.next_frame(first.sequence)
            self.assertGreater(latest.sequence, first.sequence + 1)
            self.assertFalse(latest.image.flags.writeable)
            self.assertEqual(controller.screenshot.call_args.kwargs, {"timeout": 2.0})
        self.assertFalse(capture._thread.is_alive())
        self.assertGreater(capture.stopped_at, capture.started_at)

    def test_capture_in_flight_before_action_is_not_reused(self):
        entered = threading.Event()
        release = threading.Event()
        controller = Mock()
        calls = []

        def screenshot(timeout):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                if not release.wait(1):
                    raise RuntimeError("Test capture was not released.")
            return np.zeros((10, 10, 3), np.uint8)

        controller.screenshot.side_effect = screenshot
        with ContinuousCapture(controller, max_fps=100) as capture:
            self.assertTrue(entered.wait(1))
            tap_finished = time.monotonic()
            release.set()
            frame = capture.next_frame(not_before=tap_finished, timeout=1)
            self.assertGreaterEqual(frame.sequence, 2)
            self.assertGreaterEqual(frame.started_at, tap_finished)
        self.assertFalse(capture._thread.is_alive())

    def test_worker_failure_is_propagated_not_replaced_by_stale_frame(self):
        controller = Mock()
        controller.screenshot.side_effect = RuntimeError("ADB disconnected")
        with ContinuousCapture(controller) as capture:
            with self.assertRaisesRegex(RuntimeError, "ADB disconnected"):
                capture.next_frame(timeout=1)
        self.assertFalse(capture._thread.is_alive())

    def test_context_stops_worker_when_consumer_raises(self):
        controller = Mock()
        controller.screenshot.return_value = np.zeros((10, 10, 3), np.uint8)
        capture = ContinuousCapture(controller)
        with self.assertRaisesRegex(ValueError, "consumer"):
            with capture:
                capture.next_frame()
                raise ValueError("consumer")
        self.assertFalse(capture._thread.is_alive())

    def test_timeout_does_not_return_old_frame(self):
        controller = Mock()
        controller.screenshot.side_effect = lambda timeout: np.zeros((10, 10, 3), np.uint8)
        with ContinuousCapture(controller) as capture:
            capture.next_frame()
            with self.assertRaises(TimeoutError):
                capture.next_frame(not_before=time.monotonic() + 10, timeout=.02)

    def test_closed_capture_rejects_consumers(self):
        controller = Mock()
        controller.screenshot.return_value = np.zeros((10, 10, 3), np.uint8)
        with ContinuousCapture(controller) as capture:
            capture.next_frame()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            capture.next_frame()

    def test_invalid_frame_rate_is_rejected(self):
        for rate in (0, -1):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                ContinuousCapture(Mock(), max_fps=rate)

    def test_adb_timeout_is_explicit_and_default_behavior_is_preserved(self):
        command = ["adb", "devices"]
        with patch("adb_controller.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(command, 2)), \
                self.assertRaisesRegex(RuntimeError, "timed out"):
            ADBController._run(command, timeout=2)
        with patch("adb_controller.subprocess.run",
                   return_value=Mock(returncode=0, stdout=b"ok")) as run:
            self.assertEqual(ADBController._run(command), b"ok")
        run.assert_called_once_with(
            command, capture_output=True, timeout=None, creationflags=NO_WINDOW,
        )

    def test_adb_pause_and_window_flags_are_preserved_with_timeout(self):
        command = ["adb", "devices"]
        calls = Mock()
        with patch("adb_controller.wait_if_paused") as paused, \
                patch("adb_controller.NO_WINDOW", 0x08000000), \
                patch("adb_controller.subprocess.run",
                      return_value=Mock(returncode=0, stdout=b"ok")) as run:
            calls.attach_mock(paused, "paused")
            calls.attach_mock(run, "run")
            self.assertEqual(ADBController._run(command, timeout=2), b"ok")
        self.assertEqual(calls.mock_calls, [
            call.paused(),
            call.run(command, capture_output=True, timeout=2, creationflags=0x08000000),
        ])


if __name__ == "__main__":
    unittest.main()
