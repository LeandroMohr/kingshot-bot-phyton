import threading
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from adb_controller import ContinuousCapture
from events.hidden_objects_vision import (
    CandidateFrame, ImageCandidates, Proposal, image_candidates,
)


REGION = [20, 20, 140, 140]


def object_screen():
    image = np.full((160, 160, 3), 140, np.uint8)
    cv2.rectangle(image, (65, 65), (90, 90), (20, 30, 220), -1)
    return image


class ProposalTests(unittest.TestCase):
    def test_clean_background_removes_static_high_contrast_scenery(self):
        background = object_screen()[20:140, 20:140].copy()
        screen = object_screen()
        screen[105:114, 108:117] += 18
        proposals = image_candidates(screen, REGION, background)
        self.assertEqual(len(proposals), 1)
        self.assertTrue(108 <= proposals[0].point[0] < 117)
        self.assertTrue(105 <= proposals[0].point[1] < 114)

    def test_identical_background_and_tiny_noise_do_not_generate_candidates(self):
        screen = object_screen()
        background = screen[20:140, 20:140].copy()
        self.assertEqual(image_candidates(screen, REGION, background), ())
        screen[40:50, 40:50] += 12
        screen[90, 110] = 255
        self.assertEqual(image_candidates(screen, REGION, background), ())

    def test_difference_threshold_and_small_component_boundary(self):
        background = np.full((120, 120, 3), 140, np.uint8)
        screen = np.full((160, 160, 3), 140, np.uint8)
        screen[50:52, 50:53, 2] += 13
        proposals = image_candidates(screen, REGION, background)
        self.assertEqual(len(proposals), 1)
        self.assertTrue(50 <= proposals[0].point[0] < 53)
        self.assertTrue(50 <= proposals[0].point[1] < 52)

    def test_cleared_objects_leave_only_the_remaining_difference(self):
        background = object_screen()[20:140, 20:140].copy()
        screen = object_screen()
        screen[40:55, 100:115] = 230
        screen[105:120, 40:55] = 210
        self.assertEqual(len(image_candidates(screen, REGION, background)), 2)
        screen[40:55, 100:115] = background[20:35, 80:95]
        proposals = image_candidates(screen, REGION, background)
        self.assertEqual(len(proposals), 1)
        self.assertTrue(40 <= proposals[0].point[0] < 55)
        self.assertTrue(105 <= proposals[0].point[1] < 120)

    def test_invalid_background_never_falls_back_to_contrast(self):
        for background in (np.zeros((160, 160, 3), np.uint8),
                           np.zeros((120, 120), np.uint8),
                           np.zeros((120, 120, 3), np.float32)):
            with self.subTest(shape=background.shape), self.assertRaises(ValueError):
                image_candidates(object_screen(), REGION, background)

    def test_no_map_is_needed_to_find_isolated_object_inside_region(self):
        proposals = image_candidates(object_screen(), REGION)
        self.assertTrue(proposals)
        self.assertTrue(any(65 <= p.point[0] <= 90 and 65 <= p.point[1] <= 90
                            for p in proposals[:5]))
        self.assertTrue(all(20 <= p.point[0] < 140 and 20 <= p.point[1] < 140
                            for p in proposals))
        self.assertTrue(all(type(v) is int for p in proposals for v in p.point))
        self.assertEqual(list(proposals),
                         sorted(proposals, key=lambda p: p.score, reverse=True))

    def test_uniform_scene_does_not_generate_blind_grid(self):
        self.assertEqual(image_candidates(np.full((160, 160, 3), 140, np.uint8),
                                          REGION), ())

    def test_ui_outside_scene_cannot_generate_candidates(self):
        screen = np.full((160, 160, 3), 140, np.uint8)
        cv2.rectangle(screen, (30, 145), (80, 159), (255, 255, 255), -1)
        self.assertEqual(image_candidates(screen, REGION), ())

    def test_thin_open_shape_also_generates_candidates(self):
        screen = np.full((160, 160, 3), 140, np.uint8)
        cv2.line(screen, (70, 65), (78, 100), (10, 10, 10), 3)
        self.assertTrue(image_candidates(screen, REGION))

    def test_invalid_region_raises(self):
        for region in ([0, 0, 200, 200], [-1, 0, 10, 10], [20, 20, 10, 10]):
            with self.subTest(region=region), self.assertRaises(ValueError):
                image_candidates(object_screen(), region)


class ImageWorkerTests(unittest.TestCase):
    def test_worker_uses_clean_background_for_every_frame(self):
        screen = object_screen()
        controller = Mock()
        controller.screenshot.side_effect = lambda timeout: screen
        background = screen[20:140, 20:140].copy()
        with ContinuousCapture(controller) as capture:
            with ImageCandidates(capture, REGION, background) as worker:
                self.assertEqual(worker.latest(timeout=1).proposals, ())

    def test_analysis_runs_without_consumer_and_workers_close(self):
        controller = Mock()
        controller.screenshot.side_effect = lambda timeout: object_screen()
        with ContinuousCapture(controller, max_fps=50) as capture:
            with ImageCandidates(capture, REGION) as worker:
                first = worker.latest(timeout=1)
                time.sleep(.12)
                latest = worker.latest(first.sequence + 1, timeout=1)
                self.assertGreater(latest.sequence, first.sequence)
                self.assertGreater(worker.frames, 1)
                self.assertTrue(latest.proposals)
                self.assertFalse(capture._latest.image.flags.writeable)
            self.assertFalse(worker._thread.is_alive())
        self.assertFalse(capture._thread.is_alive())

    def test_candidate_result_must_satisfy_sequence_and_action_time(self):
        worker = ImageCandidates(Mock(), REGION)
        worker._latest = CandidateFrame(5, 10, (Proposal((80, 80), 1),))
        self.assertEqual(worker.latest(5, 10, .01).sequence, 5)
        with self.assertRaises(TimeoutError):
            worker.latest(6, timeout=.01)
        with self.assertRaises(TimeoutError):
            worker.latest(not_before=11, timeout=.01)

    def test_errors_propagate_and_context_stops_worker(self):
        controller = Mock()
        controller.screenshot.side_effect = lambda timeout: object_screen()
        with ContinuousCapture(controller) as capture:
            with patch("events.hidden_objects_vision.image_candidates",
                       side_effect=ValueError("invalid pixels")):
                with self.assertRaisesRegex(RuntimeError, "invalid pixels"):
                    with ImageCandidates(capture, REGION) as worker:
                        worker.latest(timeout=1)
                self.assertFalse(worker._thread.is_alive())

    def test_capture_failure_is_not_replaced_with_empty_candidates(self):
        capture = Mock()
        capture.next_frame.side_effect = RuntimeError("ADB lost")
        with self.assertRaisesRegex(RuntimeError, "ADB lost"):
            with ImageCandidates(capture, REGION) as worker:
                worker.latest(timeout=1)

    def test_unconsumed_worker_error_is_surfaced_on_exit(self):
        capture = Mock()
        capture.next_frame.side_effect = RuntimeError("ADB lost")
        with self.assertRaisesRegex(RuntimeError, "ADB lost"):
            with ImageCandidates(capture, REGION) as worker:
                worker._thread.join(1)

    def test_close_wakes_waiting_consumer_and_rejects_results(self):
        worker = ImageCandidates(Mock(), REGION)
        waiting = threading.Event()
        errors = []

        def consume():
            waiting.set()
            try:
                worker.latest(timeout=1)
            except RuntimeError as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=consume)
        thread.start()
        self.assertTrue(waiting.wait(1))
        worker.close()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["Hidden Objects image analysis is closed."])


if __name__ == "__main__":
    unittest.main()
