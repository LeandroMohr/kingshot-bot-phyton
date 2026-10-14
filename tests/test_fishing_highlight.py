import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from events.fishing_highlight import (CatalogDetector, FishDetection, FishDetector, FishTracker,
                                     annotate_frame, fishing_hud_regions)
from adb_controller import CapturedFrame
from events.fishing_overlay import (HighlightWorker, choose_window, game_bounds,
                                    load_target_references, main, pending_entries, update_target_list)
from events.fishing_references import crop_card, export_reference


def fish_sprite():
    sprite = np.full((60, 64, 3), (170, 145, 40), np.uint8)
    cv2.ellipse(sprite, (32, 30), (24, 24), 0, 0, 360, (60, 175, 235), -1)
    cv2.ellipse(sprite, (32, 37), (23, 17), 0, 0, 360, (230, 235, 240), -1)
    cv2.circle(sprite, (42, 25), 4, (10, 15, 20), -1)
    cv2.circle(sprite, (24, 39), 2, (60, 65, 70), -1)
    return sprite


class FishingHighlightTests(unittest.TestCase):
    def test_panel_keeps_hunt_settings_visible_as_single_only(self):
        from gui import server
        with patch.object(server, "_task_info", None):
            info = server.task_info()
        for name in ("Hunt Beasts", "Hunt Terror"):
            self.assertIn(name, info)
            self.assertFalse(info[name]["loop"])
            self.assertIn("schedule", info[name])

    def test_fishing_flows_are_events_not_daily_tasks_and_use_selected_emulator(self):
        from events import EVENTS
        from tasks import TASKS
        from tasks.base import Outcome
        controller = Mock(host="127.0.0.1", port=5615)
        self.assertEqual([key for key in EVENTS if key.startswith("fishing")], ["fishing"])
        self.assertFalse(EVENTS["fishing"].requires_profile)
        self.assertNotIn(EVENTS["fishing"], TASKS)
        ordered = Mock()
        with patch.object(EVENTS["fishing"], "update_collection", True), \
            patch("events.fishing_tournament.map_fishing_collection") as mapping, \
                patch("events.fishing_overlay.main") as overlay, \
                patch("events.fishing_tournament.start_trial_stage") as trial, \
                patch("events.fishing_tournament.reset_fishing_round") as retreat:
            ordered.attach_mock(mapping, "mapping")
            ordered.attach_mock(overlay, "overlay")
            self.assertEqual(EVENTS["fishing"].execute(controller), Outcome.SUCCESS)
        mapping.assert_called_once_with(controller)
        overlay.assert_called_once_with(["--host", "127.0.0.1", "--port", "5615"])
        self.assertEqual([item[0] for item in ordered.mock_calls], ["mapping", "overlay"])
        trial.assert_not_called()
        retreat.assert_not_called()

    def test_fishing_defaults_to_saved_collection_without_scanning(self):
        from events.fishing_tournament import FishingFlow
        from tasks.base import Outcome
        for answers in ([""], [None], ["1"]):
            with self.subTest(answers=answers), \
                    patch("events.fishing_tournament.sys.stdin") as stdin, \
                    patch("events.fishing_tournament.console.timed_input", side_effect=answers), \
                    patch("events.fishing_tournament.map_fishing_collection") as mapping, \
                    patch("events.fishing_overlay.main") as overlay:
                stdin.isatty.return_value = True
                flow = FishingFlow()
                flow.update_collection = True
                self.assertEqual(flow.choose_options(), "start")
                self.assertEqual(flow.execute(Mock(host="127.0.0.1", port=5555)), Outcome.SUCCESS)
                mapping.assert_not_called()
                overlay.assert_called_once_with(["--host", "127.0.0.1", "--port", "5555"])

    def test_fishing_updates_only_when_explicitly_selected(self):
        from events.fishing_tournament import FishingFlow
        with patch("events.fishing_tournament.sys.stdin") as stdin, \
                patch("events.fishing_tournament.console.timed_input", side_effect=["invalid", "2"]):
            stdin.isatty.return_value = True
            flow = FishingFlow()
            self.assertEqual(flow.choose_options(), "start")
            self.assertTrue(flow.update_collection)

    def test_fishing_noninteractive_start_uses_saved_collection(self):
        from events.fishing_tournament import FishingFlow
        with patch("events.fishing_tournament.sys.stdin") as stdin, \
                patch("events.fishing_tournament.console.timed_input") as prompt:
            stdin.isatty.return_value = False
            flow = FishingFlow()
            self.assertEqual(flow.choose_options(), "start")
            self.assertFalse(flow.update_collection)
            prompt.assert_not_called()

    def test_fishing_submenu_supports_back_to_events_and_quit(self):
        import main as bot_main
        from events import EVENTS
        from tasks import TASKS
        index = list(EVENTS).index("fishing") + 1
        for answers in (["3", str(index), "0", "0", "q"],
                        ["3", str(index), "q"]):
            with self.subTest(answers=answers), \
                    patch("main.sys.stdin") as stdin, \
                    patch("main.console.timed_input", side_effect=answers):
                stdin.isatty.return_value = True
                self.assertEqual(bot_main.select_active_tasks(TASKS, list(EVENTS.values())), [])

    def test_cli_fishing_asks_for_options_and_quit_does_not_launch_overlay(self):
        import main as bot_main
        from events import EVENTS
        with patch.object(EVENTS["fishing"], "choose_options", return_value="quit") as options, \
                patch("main.ensure_game_ready") as ready, \
                patch("events.fishing_overlay.main") as overlay:
            bot_main.run_loop(Mock(port=5555), event=EVENTS["fishing"])
        options.assert_called_once()
        ready.assert_not_called()
        overlay.assert_not_called()

    def test_single_task_menu_and_cli_keep_hunting_available(self):
        import main as bot_main
        from tasks import ALL_TASKS, TASKS
        index = next(index for index, task in enumerate(ALL_TASKS, 1) if task.name == "Hunt Beasts")
        with patch("main.sys.stdin") as stdin, \
                patch("main.console.timed_input", side_effect=["2", str(index)]):
            stdin.isatty.return_value = True
            selected = bot_main.select_active_tasks(TASKS, [], ALL_TASKS)
        self.assertEqual([task.name for task in selected], ["Hunt Beasts"])
        with patch("main.sys.argv", ["main.py", "--port", "5555", "--task", "Hunt Terror"]), \
                patch("main.ADBController") as controller, patch("main.run_loop") as run:
            bot_main.main()
        self.assertEqual([task.name for task in run.call_args.args[1]], ["Hunt Terror"])

    def test_single_only_hunting_finishes_without_entering_recurring_loop(self):
        import main as bot_main
        task = Mock(loop=False)
        task.name = "Hunt Beasts"
        controller = Mock(port=5555)
        with patch("main.SINGLE_ONLY_TASKS", [task]), \
                patch("main.ensure_game_ready"), patch("main.go_to_home_screen"), \
                patch("main.read_player_profile"), patch("main.order_tasks", return_value=[task]), \
                patch("main.skip_disabled", return_value=([task], [])), \
                patch("main.check_task") as check, patch("main.time.sleep") as wait:
            bot_main.run_loop(controller, [task])
        check.assert_called_once()
        task.mark_done.assert_called_once()
        wait.assert_not_called()

    def test_hunting_is_single_only_and_excluded_from_default_tasks(self):
        from tasks import ALL_TASKS, SINGLE_ONLY_TASKS, TASKS
        names = {task.name for task in SINGLE_ONLY_TASKS}
        self.assertEqual(names, {"Hunt Beasts", "Hunt Terror"})
        self.assertTrue(names.isdisjoint({task.name for task in TASKS}))
        self.assertTrue(names.issubset({task.name for task in ALL_TASKS}))
        self.assertTrue(all(task.loop is False for task in SINGLE_ONLY_TASKS))

    def test_default_startup_refreshes_pending_selection_without_native_blowfish(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / "knowledge").mkdir()
            (base / "memory").mkdir()
            reference_dir = base / "templates/fishing_references"
            reference_dir.mkdir(parents=True)
            cv2.imwrite(str(reference_dir / "object.png"), np.zeros((100, 100, 3), np.uint8))
            entries = [{"id": 10024, "name": "Blowfish", "category": "Catches", "points": 10, "depth": 10},
                       {"id": 40001, "name": "Unknown object", "category": "Memorabilia", "points": 70, "depth": 500}]
            (base / "knowledge/fishing_catalog.json").write_text(json.dumps({"entries": entries}))
            (base / "memory/fishing_collection_5555.json").write_text(
                json.dumps({"entries": {"10024": {"captured": True}}}))
            (reference_dir / "index.json").write_text(json.dumps({"entries": [
                {"id": 10024, "file": "blowfish.png", "available_seasons": ["autumn"]},
                {"id": 40001, "file": "object.png", "available_seasons": ["winter"]}]}))
            with patch("events.fishing_overlay.config.BASE_DIR", base), \
                    patch("sys.argv", ["overlay", "--port", "5555"]), \
                    patch("events.fishing_overlay.CatalogDetector") as catalog, \
                    patch("events.fishing_overlay.FishDetector") as native, \
                    patch("events.fishing_overlay.run_overlay") as overlay:
                catalog.return_value.rejected = {}
                main()
                native.assert_not_called()
                self.assertEqual(set(catalog.call_args.args[0]), {"Unknown object"})
                self.assertEqual(overlay.call_args.kwargs["target_statuses"], {"Unknown object": "unknown"})
            selection = json.loads((base / "memory/fishing_highlight_targets_5555.json").read_text())
            self.assertEqual([entry["id"] for entry in selection["entries"]], [40001])

    def test_empty_catalog_detector_allows_completion_without_restoring_blowfish(self):
        detector = CatalogDetector({})
        self.assertEqual(detector.detect(np.zeros((960, 540, 3), np.uint8)), [])

    def test_target_loader_only_loads_enabled_references_and_preserves_unknown_status(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            cv2.imwrite(str(base / "object.png"), np.zeros((100, 100, 3), np.uint8))
            path = base / "targets.json"
            path.write_text(json.dumps({"entries": [
                {"name": "Unknown object", "enabled": True,
                 "capture_status": "unknown", "reference": "object.png"},
                {"name": "Disabled", "enabled": False, "reference": "absent.png"}]}))
            references, statuses = load_target_references(path, base)
            self.assertEqual(references, {"Unknown object": base / "object.png"})
            self.assertEqual(statuses, {"Unknown object": "unknown"})

    def test_catalog_detector_matches_scaled_artwork_and_ignores_hud(self):
        rng = np.random.default_rng(7)
        card = np.full((220, 280, 3), (190, 160, 70), np.uint8)
        texture = rng.integers(20, 230, (100, 160, 3), dtype=np.uint8)
        texture = cv2.GaussianBlur(texture, (3, 3), 0)
        card[60:160, 60:220] = texture
        scene = np.full((960, 540, 3), (170, 130, 40), np.uint8)
        scaled = cv2.resize(texture, (112, 70))
        scene[40:110, 10:122] = scaled
        scene[300:370, 200:312] = scaled
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "object.png"
            cv2.imwrite(str(path), card)
            detector = CatalogDetector({"Unknown object": path}, threshold=.8)
            found = detector.detect(scene, fishing_hud_regions((540, 960)))
            self.assertEqual(detector.detect(np.zeros_like(scene)), [])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].name, "Unknown object")
        self.assertAlmostEqual(found[0].box[0], 200, delta=4)
        self.assertAlmostEqual(found[0].box[1], 300, delta=4)

    def test_target_list_maps_pending_references_and_preserves_disabled_entries(self):
        entries = [{"id": 1, "name": "Unknown object", "category": "Memorabilia",
                    "points": 70, "depth": 500},
                   {"id": 2, "name": "Missing fish", "category": "Catches",
                    "points": 150, "depth": 530}]
        references = {"entries": [{"id": 1, "file": "objects/1_object.png",
                                   "available_seasons": ["winter"]},
                                  {"id": 2, "file": "fish/2_fish.png",
                                   "available_seasons": ["autumn"]}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "targets.json"
            path.write_text(json.dumps({"entries": [{"id": 1, "enabled": False}]}))
            result = update_target_list(entries, {"2": {"captured": False}}, references, path)
            self.assertEqual(json.loads(path.read_text()), result)
            self.assertEqual(result["entries"][0]["capture_status"], "unknown")
            self.assertFalse(result["entries"][0]["enabled"])
            self.assertTrue(result["entries"][1]["enabled"])
            self.assertEqual(result["entries"][1]["capture_status"], "missing")
            self.assertFalse(result["calibrated_for_gameplay"])
            refreshed = update_target_list(entries, {"2": {"captured": True}}, references, path)
            self.assertEqual([entry["id"] for entry in refreshed["entries"]], [1])
            complete = update_target_list(entries, {"1": {"captured": True},
                                                   "2": {"captured": True}}, references, path)
            self.assertEqual(complete["entries"], [])

    def test_worker_uses_original_frame_without_publishing_brightness_layer(self):
        controller, detector, capture, tracker = Mock(), Mock(), Mock(), Mock()
        detector.detect.return_value = []
        tracker.update.return_value = []
        worker = HighlightWorker(controller, detector)
        image = np.zeros((960, 540, 3), np.uint8)
        image[300:400, 200:300] = (2, 10, 24)
        image.setflags(write=False)

        def next_frame(sequence):
            worker.stop.set()
            return CapturedFrame(1, 10, 10.1, image)

        capture.next_frame.side_effect = next_frame
        with patch("events.fishing_overlay.ContinuousCapture") as factory, \
                patch("events.fishing_overlay.FishTracker", return_value=tracker), \
                patch("events.fishing_overlay.has_pause_icon", return_value=True):
            factory.return_value.__enter__.return_value = capture
            worker.run()
        self.assertIsNone(worker.error)
        self.assertNotIn("brightness_png", worker.state)
        self.assertIs(detector.detect.call_args.args[0], image)
        self.assertIs(tracker.update.call_args.args[0], image)
        self.assertEqual(int(image[350, 250, 2]), 24)

    def test_overlay_worker_recovers_after_fresh_frame_timeout(self):
        controller, detector, capture, tracker = Mock(), Mock(), Mock(), Mock()
        detector.detect.return_value = []
        tracker.update.return_value = []
        worker = HighlightWorker(controller, detector)
        image = np.zeros((960, 540, 3), np.uint8)
        calls = []

        def next_frame(sequence):
            calls.append(sequence)
            if len(calls) == 1:
                raise TimeoutError("No fresh frame")
            worker.stop.set()
            return CapturedFrame(1, 10, 10.1, image)

        capture.next_frame.side_effect = next_frame
        with patch("events.fishing_overlay.ContinuousCapture") as factory, \
                patch("events.fishing_overlay.FishTracker", return_value=tracker), \
                patch("events.fishing_overlay.has_pause_icon", return_value=True):
            factory.return_value.__enter__.return_value = capture
            worker.run()
            factory.assert_called_once_with(controller, max_timeout_retries=2)
        self.assertIsNone(worker.error)
        self.assertEqual(worker.frames, 1)
        tracker.clear.assert_called_once()
        self.assertEqual(worker.state["completed_at"], 10.1)

    def test_overlay_worker_resets_tracking_after_capture_gap(self):
        controller, detector, capture, tracker = Mock(), Mock(), Mock(), Mock()
        detector.detect.return_value = []
        tracker.update.return_value = []
        worker = HighlightWorker(controller, detector)
        image = np.zeros((960, 540, 3), np.uint8)
        frames = [CapturedFrame(1, 10, 10.1, image), CapturedFrame(2, 11, 11.1, image)]

        def next_frame(sequence):
            frame = frames.pop(0)
            if not frames:
                worker.stop.set()
            return frame

        capture.next_frame.side_effect = next_frame
        with patch("events.fishing_overlay.ContinuousCapture") as factory, \
                patch("events.fishing_overlay.FishTracker", return_value=tracker), \
                patch("events.fishing_overlay.has_pause_icon", return_value=True):
            factory.return_value.__enter__.return_value = capture
            worker.run()
        self.assertIsNone(worker.error)
        self.assertEqual(worker.frames, 2)
        tracker.clear.assert_called_once()

    def test_detector_ignores_counter_and_pause_regions_but_detects_playfield(self):
        sprite = fish_sprite()
        image = np.full((960, 540, 3), (170, 145, 40), np.uint8)
        image[40:100, 20:84] = sprite
        image[0:60, 476:540] = sprite
        image[300:360, 200:264] = sprite
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fish.png"
            cv2.imwrite(str(path), sprite)
            detector = FishDetector({"Blowfish": path}, threshold=.98, scales=(1.0,))
            detected = detector.detect(image, excluded_regions=fishing_hud_regions((540, 960)))
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0].box[:2], (200, 300))

    def test_tracker_rejects_hud_detections_and_removes_tracks_entering_hud(self):
        tracker = FishTracker()
        image = np.zeros((960, 540, 3), np.uint8)
        excluded = fishing_hud_regions((540, 960))
        detections = [FishDetection("Blowfish", (20, 30, 64, 60), 1),
                      FishDetection("Blowfish", (490, 10, 40, 40), 1),
                      FishDetection("Blowfish", (200, 210, 64, 60), 1)]
        tracks = tracker.update(image, detections, excluded_regions=excluded)
        self.assertEqual(len(tracks), 1)
        tracks[0].velocity = (-80, -150)
        self.assertEqual(tracker.update(image, [], excluded_regions=excluded), [])

    def test_tracker_expires_even_if_optical_flow_keeps_following_static_pixels(self):
        image = np.zeros((240, 320, 3), np.uint8)
        image[50:110, 100:164] = fish_sprite()
        tracker = FishTracker(max_missed_frames=3)
        tracker.update(image, [FishDetection("Blowfish", (100, 50, 64, 60), 1)])
        for missed in range(1, 4):
            tracks = tracker.update(image, [])
            self.assertEqual(len(tracks), 1)
            self.assertEqual(tracks[0].missed_frames, missed)
        self.assertEqual(tracker.update(image, []), [])

    def test_detector_reconfirmation_resets_track_expiration(self):
        image = np.zeros((240, 320, 3), np.uint8)
        detection = FishDetection("Blowfish", (100, 50, 64, 60), 1)
        tracker = FishTracker(max_missed_frames=1)
        identifier = tracker.update(image, [detection])[0].identifier
        tracker.update(image, [])
        refreshed = tracker.update(image, [detection])[0]
        self.assertEqual(refreshed.identifier, identifier)
        self.assertEqual(refreshed.missed_frames, 0)
        self.assertEqual(len(tracker.update(image, [])), 1)
        self.assertEqual(tracker.update(image, []), [])

    def test_hud_exclusion_scales_with_native_frame_dimensions(self):
        self.assertEqual(fishing_hud_regions((1080, 1920)),
                         ((0, 0, 300, 280), (980, 0, 100, 110)))

    def test_pending_targets_include_unknown_categories_without_depth_or_season_filter(self):
        entries = [{"id": 1, "category": "Catches", "depth": 530, "seasons": [1]},
                   {"id": 2, "category": "Memorabilia"},
                   {"id": 3, "category": "Mermaids"},
                   {"id": 4, "category": "Ocean Chests"},
                   {"id": 5, "category": "Catches"}]
        collection = {"1": {"captured": False}, "3": {"captured": None},
                      "5": {"captured": True}}
        selected = pending_entries(entries, collection)
        self.assertEqual([entry["id"] for entry in selected], [1, 2, 3, 4])
        self.assertEqual([entry["capture_status"] for entry in selected],
                         ["missing", "unknown", "unknown", "unknown"])
        self.assertNotIn("capture_status", entries[0])

    def test_handbook_crop_excludes_border_and_footer_without_mutating_source(self):
        image = np.zeros((423, 350, 4), np.uint8)
        image[110:275, 85:270] = (30, 160, 230, 255)
        image[315:390, 240:315] = (0, 255, 0, 255)
        image.setflags(write=False)
        crop, bounds = crop_card(image)
        self.assertEqual(bounds, (7, 85, 343, 309))
        self.assertEqual(crop.shape, (224, 336, 4))
        self.assertEqual(np.count_nonzero(crop[:, :, 3]), 165 * 185)
        self.assertFalse(np.shares_memory(crop, image))

    def test_handbook_export_maps_name_seasons_and_unknown_collection_state(self):
        entry = {"id": 30001, "name": "Ocean Resource Chest", "slug": "ocean-resource-chest",
                 "category": "Ocean Chests", "points": None, "depth": 200,
                 "seasons": [2, 3, 4], "image": "/images/tools/fishing-handbook/chest.webp"}
        image = np.full((423, 350, 3), 150, np.uint8)
        with tempfile.TemporaryDirectory() as folder:
            reference = export_reference(entry, image, Path(folder), {})
            saved = cv2.imread(str(Path(folder) / reference["file"]))
        self.assertEqual(reference["file"], "chests/30001_ocean-resource-chest.png")
        self.assertEqual(reference["name"], entry["name"])
        self.assertEqual(reference["available_seasons"], ["spring", "summer", "autumn"])
        self.assertEqual(reference["capture_status"], "unknown")
        self.assertIsNone(reference["points"])
        self.assertFalse(reference["calibrated_for_gameplay"])
        self.assertFalse(reference["background_removed"])
        self.assertEqual(saved.shape, (224, 336, 3))

    def test_handbook_crop_rejects_unreadable_or_small_images(self):
        for image in (None, np.zeros((40, 40, 3), np.uint8), np.zeros((423, 350), np.uint8)):
            with self.subTest(shape=None if image is None else image.shape):
                with self.assertRaises(ValueError):
                    crop_card(image)

    def test_overlay_fits_game_and_respects_toolbar_insets(self):
        viewport = game_bounds({"X": 641, "Y": 33, "Width": 491, "Height": 848},
                               (540, 960), (0, 30, 32, 0))
        self.assertAlmostEqual(viewport["Width"] / viewport["Height"], 540 / 960)
        self.assertGreaterEqual(viewport["X"], 641)
        self.assertGreaterEqual(viewport["Y"], 63)
        self.assertLessEqual(viewport["X"] + viewport["Width"], 1100)

    def test_overlay_requires_explicit_window_when_multiple_emulators_exist(self):
        windows = [{"kCGWindowNumber": identifier, "kCGWindowOwnerName": "BlueStacks",
                    "kCGWindowBounds": {"Width": 500, "Height": 900}}
                   for identifier in (10, 20)]
        with self.assertRaisesRegex(RuntimeError, "--window-id"):
            choose_window(windows)
        self.assertEqual(choose_window(windows, 20)["kCGWindowNumber"], 20)

    def test_detector_marks_multiple_and_mirrored_fish_once_each(self):
        sprite = fish_sprite()
        image = np.full((240, 320, 3), (170, 145, 40), np.uint8)
        image[30:90, 20:84] = sprite
        image[130:190, 190:254] = cv2.flip(sprite, 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fish.png"
            cv2.imwrite(str(path), sprite)
            detector = FishDetector({"Blowfish": path}, threshold=.98, scales=(1.0,))
            detections = detector.detect(image)
        self.assertEqual(len(detections), 2)
        self.assertEqual(sorted((round(item.box[0]), round(item.box[1])) for item in detections),
                         [(20, 30), (190, 130)])

    def test_tracker_preserves_identity_on_motion_and_detector_miss(self):
        sprite = fish_sprite()
        first = np.zeros((240, 320, 3), np.uint8)
        second = first.copy()
        first[40:100, 50:114] = sprite
        second[45:105, 57:121] = sprite
        tracker = FishTracker()
        track = tracker.update(first, [FishDetection("Blowfish", (50, 40, 64, 60), 1)])[0]
        moved = tracker.update(second, [])[0]
        self.assertEqual(moved.identifier, track.identifier)
        self.assertAlmostEqual(moved.box[0], 57, delta=1)
        self.assertAlmostEqual(moved.box[1], 45, delta=1)

    def test_tracks_remain_when_partially_visible_and_leave_at_frame_edge(self):
        tracker = FishTracker()
        image = np.zeros((100, 100, 3), np.uint8)
        tracker.update(image, [FishDetection("Blowfish", (-20, 10, 40, 40), 1)])
        self.assertEqual(len(tracker.update(image, [])), 1)
        tracker.tracks[0].velocity = (-25, 0)
        self.assertEqual(tracker.update(image, []), [])

    def test_annotation_does_not_mutate_capture(self):
        image = np.zeros((100, 100, 3), np.uint8)
        image.setflags(write=False)
        tracker = FishTracker()
        tracks = tracker.update(image, [FishDetection("Blowfish", (20, 20, 50, 50), 1)])
        rendered = annotate_frame(image, tracks)
        self.assertTrue(np.any(rendered))
        self.assertFalse(np.any(image))


if __name__ == "__main__":
    unittest.main()