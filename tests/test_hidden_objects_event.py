import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

import main
from adb_controller import CapturedFrame
from tasks import TASKS
from events import EVENTS
from events.castle_battle import CastleBattleEvent
from tasks.base import Outcome
from events.hidden_objects import (
    HiddenObjectsEvent, ObjectMap, Target, normalize_name,
    progress_count, read_targets, remaining_seconds, is_timeout, round_result, RoundCapture,
    _changed_at_click,
)
from vision import Match
from events.hidden_objects_vision import CandidateFrame, Proposal


REGIONS = [[20, 855, 178, 896], [191, 855, 350, 896], [365, 855, 520, 896]]
PROGRESS = [20, 923, 519, 937]


def screen_with_progress(count, total=9):
    screen = np.full((960, 540, 3), (180, 120, 60), dtype=np.uint8)
    for i in range(count):
        x = 20 + round(i * 499 / total)
        end = 20 + round((i + 1) * 499 / total)
        screen[923:937, x + 1:end - 1] = (65, 200, 255)
    return screen


def result_screen(result):
    screen = screen_with_progress(0)
    screen[0, 0, 0] = 1 if result == Outcome.SUCCESS else 2
    return screen


def event_match(screen, name, *args):
    flag = screen[0, 0, 0]
    if name == "hidden_objects_success.png":
        return Match(flag == 1, 1)
    if name.startswith("hidden_objects_timeout"):
        return Match(flag == 2, 1)
    return Match(name == "hidden_objects_round_marker.png" and flag not in (1, 2), 1)


def mock_map(**kwargs):
    mapping = Mock(**kwargs)
    mapping.was_missed.return_value = False
    mapping.background.return_value = None
    return mapping


def screen_with_hit(count, point, total=9):
    image = screen_with_progress(count, total)
    x, y = point
    image[y - 5:y + 6, x - 5:x + 6] = 255
    return image


class ObjectMapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "objects.json"
        self.mapping = ObjectMap(learned=self.path)

    def test_name_normalization_and_observed_ocr_aliases(self):
        self.assertEqual(normalize_name("  BÚSSOLA\n"), "bussola")
        self.assertEqual(self.mapping.coordinates("forest", "Machada"), (114, 669))
        self.assertEqual(self.mapping.coordinates("forest", "Copo de Aqua"), (365, 575))
        self.assertIsNone(self.mapping.coordinates("forest", "Novo Objeto"))

    def test_forest_background_has_exact_crop_size_and_is_cached_read_only(self):
        image = self.mapping.background("forest")
        self.assertEqual(image.shape, (735, 450, 3))
        self.assertFalse(image.flags.writeable)
        self.assertIs(self.mapping.background("forest"), image)

    def test_scene_without_background_preserves_legacy_search(self):
        self.mapping.reference["scenes"]["forest"].pop("background")
        self.assertIsNone(self.mapping.background("forest"))

    def test_configured_missing_background_raises(self):
        self.mapping.reference["scenes"]["forest"]["background"] = "missing-background.png"
        with self.assertRaisesRegex(FileNotFoundError, "Clean background"):
            self.mapping.background("forest")

    def test_corrupt_or_wrong_size_background_raises(self):
        for image in (None, np.zeros((734, 450, 3), np.uint8)):
            with self.subTest(image_is_none=image is None), \
                    patch("events.hidden_objects.cv2.imread", return_value=image), \
                    self.assertRaises(ValueError):
                self.mapping.background("forest")

    def test_all_mapped_objects_have_english_names_at_the_same_coordinates(self):
        names = {
            "Small Bag": "Bolsa Pequena", "Compass": "Bússola", "Rope": "Corda",
            "Pinecone": "Pinha", "Book": "Livro", "Dagger": "Adaga",
            "Squirrel": "Esquilo", "Clay Jar": "Jarro de Argila", "Boat": "Barco",
            "Axe": "Machado", "Grilled Fish": "Peixe Grelhado", "Fence": "Cerca",
            "Bird": "Pássaro", "Slingshot": "Estilingue", "Saw": "Serra",
            "Footprint": "Pegada", "Grilled Skewer": "Espetinho Grelhado",
            "Scroll": "Pergaminho", "Shovel": "Pá", "Cup of Water": "Copo de Água",
            "Feather": "Pena", "Barrel": "Barril", "Hammer": "Martelo",
            "Lantern": "Lampião", "Potatoes": "Batatas", "Dog": "Cachorro",
            "Heart": "Coração", "Crutch": "Muleta",
            "Patch": "Remendo",
            "Brush": "Pincel",
        }
        self.assertEqual(set(names.values()),
                         set(self.mapping.reference["scenes"]["forest"]["objects"]))
        for english, portuguese in names.items():
            with self.subTest(english=english):
                self.assertEqual(self.mapping.canonical_name(english), portuguese)
                self.assertEqual(self.mapping.coordinates("forest", english),
                                 self.mapping.coordinates("forest", portuguese))

    def test_english_synonyms_case_and_whitespace_normalize(self):
        for english, portuguese in [
            ("  PINE\nCONE  ", "Pinha"), ("small pouch", "Bolsa Pequena"),
            ("Clay Pot", "Jarro de Argila"), ("Glass of Water", "Copo de Água"),
            ("Walking Stick", "Muleta"), ("Spade", "Pá"),
            ("Beat", "Barco"), ("Deg", "Cachorro"), ("Potatces", "Batatas"),
            ("Clay Jug", "Jarro de Argila"),
        ]:
            with self.subTest(english=english):
                self.assertEqual(self.mapping.coordinates("forest", english),
                                 self.mapping.coordinates("forest", portuguese))

    def test_english_confirmation_updates_portuguese_record_without_duplicates(self):
        self.mapping.queue("forest", "Heart")
        self.mapping.queue("forest", "Coração")
        self.mapping.confirm("forest", "HEART", (159, 125))
        loaded = ObjectMap(learned=self.path)
        bucket = loaded.learned["scenes"]["forest:540x960"]
        self.assertEqual(bucket["pending"], [])
        self.assertEqual(list(bucket["objects"]), ["coracao"])
        self.assertEqual(bucket["objects"]["coracao"]["name"], "Coração")
        self.assertEqual(loaded.coordinates("forest", "Heart"),
                         loaded.coordinates("forest", "Coração"))

    def test_english_candidate_lookup_uses_portuguese_candidates(self):
        self.assertEqual(self.mapping.candidates("forest", "Heart"),
                         self.mapping.candidates("forest", "Coração"))

    def test_new_brush_candidates_reuse_user_identified_location(self):
        self.assertEqual(self.mapping.candidates("forest", "Brush")[0], (87, 430))
        self.assertEqual(self.mapping.candidates("forest", "Pincel")[0], (87, 430))

    def test_pending_english_names_added_before_alias_do_not_duplicate(self):
        self.mapping.learned["scenes"]["forest:540x960"] = {
            "objects": {}, "pending": ["Brush"]}
        self.mapping.queue("forest", "Pincel")
        self.assertEqual(self.mapping.learned["scenes"]["forest:540x960"]["pending"],
                         ["Brush"])
        self.mapping.confirm("forest", "Brush", (87, 430))
        self.assertEqual(self.mapping.learned["scenes"]["forest:540x960"]["pending"], [])

    def test_alias_added_after_learning_merges_old_english_record(self):
        self.mapping.learned["scenes"]["forest:540x960"] = {
            "objects": {"clay jug": {"name": "Clay Jug", "point": [426, 438]}},
            "pending": [],
        }
        self.mapping.confirm("forest", "Clay Jug", (426, 438))
        self.assertEqual(
            list(self.mapping.learned["scenes"]["forest:540x960"]["objects"]),
            ["jarro de argila"])

    def test_confirming_hit_clears_pending_names_now_present_in_reference(self):
        self.mapping.learned["scenes"]["forest:540x960"] = {
            "objects": {}, "pending": ["Brush", "Objeto Novo"]}
        self.mapping.confirm("forest", "Rope", (416, 634))
        self.assertEqual(self.mapping.learned["scenes"]["forest:540x960"]["pending"],
                         ["Objeto Novo"])

    def test_unknown_name_persisted_without_unverified_coordinates(self):
        self.mapping.queue("forest", "Objeto Novo")
        self.mapping.queue("forest", "OBJETO NOVO")
        loaded = ObjectMap(learned=self.path)
        self.assertIsNone(loaded.coordinates("forest", "Objeto Novo"))
        self.assertEqual(loaded.learned["scenes"]["forest:540x960"]["pending"],
                         ["Objeto Novo"])

    def test_confirmed_coordinate_survives_reload_and_clears_pending(self):
        self.mapping.queue("forest", "Coracgao")
        self.mapping.confirm("forest", "Coração", (159, 125))
        loaded = ObjectMap(learned=self.path)
        self.assertEqual(loaded.coordinates("forest", "Coracgao"), (159, 125))
        self.assertEqual(loaded.learned["scenes"]["forest:540x960"]["pending"], [])
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_invalid_coordinates_are_not_saved(self):
        for point in [(0, 0), (540, 960), (100.5, 100), (True, 100)]:
            with self.subTest(point=point), self.assertRaises(ValueError):
                self.mapping.confirm("forest", "Bad", point)
        self.assertFalse(self.path.exists())

    def test_corrupt_memory_raises_instead_of_silently_resetting(self):
        self.path.write_text("{broken")
        with self.assertRaises(json.JSONDecodeError):
            ObjectMap(learned=self.path)
        self.assertEqual(self.path.read_text(), "{broken")

    def test_candidate_locations_do_not_become_verified_coordinates(self):
        self.assertEqual(self.mapping.candidates("forest", "Coração")[0], (159, 125))
        self.assertEqual(self.mapping.candidates("forest", "Muleta")[0], (72, 554))
        self.mapping.reference["name_candidates"]["Objeto Novo"] = [[159, 125]]
        self.assertEqual(self.mapping.candidates("forest", "Objeto Novo")[0], (159, 125))
        self.assertIsNone(self.mapping.coordinates("forest", "Objeto Novo"))

    def test_verified_misses_survive_reload_share_aliases_and_have_small_radius(self):
        self.mapping.record_miss("forest", "Heart", (100, 200))
        loaded = ObjectMap(learned=self.path)
        self.assertTrue(loaded.was_missed("forest", "Coração", (108, 200)))
        self.assertTrue(loaded.was_missed("forest", "HEART", (100, 200)))
        self.assertFalse(loaded.was_missed("forest", "Heart", (109, 200)))
        self.assertFalse(loaded.was_missed("forest", "Heart", (108, 208)))
        self.assertFalse(loaded.was_missed("forest", "Compass", (100, 200)))
        self.assertFalse(loaded.was_missed("other-scene", "Heart", (100, 200)))
        loaded.reference["resolution"] = [1080, 1920]
        self.assertFalse(loaded.was_missed("forest", "Heart", (100, 200)))

    def test_nearby_misses_are_deduplicated_and_never_become_coordinates(self):
        self.mapping.record_miss("forest", "Unknown", (100, 200))
        self.mapping.record_miss("forest", "UNKNOWN", (105, 200))
        self.mapping.record_miss("forest", "Unknown", (120, 200))
        bucket = self.mapping.learned["scenes"]["forest:540x960"]
        self.assertEqual(bucket["misses"]["unknown"], [[100, 200], [120, 200]])
        self.assertIsNone(self.mapping.coordinates("forest", "Unknown"))
        self.mapping.queue("forest", "Unknown")
        self.assertEqual(bucket["pending"], ["Unknown"])

    def test_confirming_name_clears_its_misses_but_preserves_other_names(self):
        self.mapping.record_miss("forest", "Heart", (100, 200))
        self.mapping.record_miss("forest", "Compass", (100, 200))
        self.mapping.confirm("forest", "Coração", (159, 125))
        self.assertFalse(self.mapping.was_missed("forest", "Heart", (100, 200)))
        self.assertTrue(self.mapping.was_missed("forest", "Compass", (100, 200)))
        self.assertEqual(self.mapping.coordinates("forest", "Heart"), (159, 125))

    def test_old_memory_without_misses_remains_compatible(self):
        self.mapping.queue("forest", "New")
        self.assertNotIn("misses", self.mapping.learned["scenes"]["forest:540x960"])
        loaded = ObjectMap(learned=self.path)
        self.assertFalse(loaded.was_missed("forest", "New", (100, 200)))
        loaded.record_miss("forest", "New", (100, 200))
        self.assertTrue(ObjectMap(learned=self.path).was_missed("forest", "New", (100, 200)))

    def test_invalid_miss_coordinates_are_not_persisted(self):
        with self.assertRaises(ValueError):
            self.mapping.record_miss("forest", "New", (540, 960))
        self.assertFalse(self.path.exists())


class RecognitionTests(unittest.TestCase):
    def test_scene_change_elsewhere_is_not_attributed_to_the_bot_click(self):
        before = screen_with_progress(0)
        self.assertFalse(_changed_at_click(
            before, screen_with_hit(1, (159, 125)), (120, 300), [45, 60, 495, 795]))
        self.assertTrue(_changed_at_click(
            before, screen_with_hit(1, (159, 125)), (159, 125), [45, 60, 495, 795]))
        after = screen_with_hit(2, (159, 125))
        after[300:311, 120:131] = 255
        self.assertFalse(_changed_at_click(before, after, (159, 125), [45, 60, 495, 795]))

    def test_ui_only_or_large_overlay_change_is_not_an_object_at_the_click(self):
        before = screen_with_progress(0)
        after = screen_with_progress(1)
        self.assertFalse(_changed_at_click(before, after, (159, 125), [45, 60, 495, 795]))
        after[60:795, 45:495] = 0
        self.assertFalse(_changed_at_click(before, after, (159, 125), [45, 60, 495, 795]))

    def test_timeout_recognized_in_either_language(self):
        for marker in ["hidden_objects_timeout.png", "hidden_objects_timeout_en.png"]:
            with self.subTest(marker=marker), patch(
                    "events.hidden_objects.find_template",
                    side_effect=lambda s, name: Match(name == marker, 1)):
                self.assertTrue(is_timeout(screen_with_progress(0)))

    def test_active_round_is_not_a_timeout(self):
        with patch("events.hidden_objects.find_template", return_value=Match(False, 0)):
            self.assertFalse(is_timeout(screen_with_progress(0)))

    def test_timer_reads_actual_remaining_budget(self):
        for raw, expected in [("60s", 60), ("90s", 90), ("120s", 120), ("7s", 7), ("0", 0)]:
            with self.subTest(raw=raw), patch(
                    "events.hidden_objects.pytesseract.image_to_string",
                    return_value=raw):
                self.assertEqual(remaining_seconds(
                    screen_with_progress(0), [50, 816, 100, 841]), expected)

    def test_invalid_timer_does_not_silently_grant_sixty_seconds(self):
        for raw in ["", "1000s", "-1s", "clock"]:
            with self.subTest(raw=raw), patch(
                    "events.hidden_objects.pytesseract.image_to_string",
                    return_value=raw), self.assertRaises(ValueError):
                remaining_seconds(screen_with_progress(0), [50, 816, 100, 841])

    def test_counts_variable_number_of_progress_blocks(self):
        for total in (9, 12, 15, 18):
            for count in range(total + 1):
                with self.subTest(total=total, count=count):
                    self.assertEqual(progress_count(screen_with_progress(count, total),
                                                    PROGRESS), count)

    def test_only_explicit_success_or_failure_is_a_round_result(self):
        with patch("events.hidden_objects.find_template", side_effect=event_match):
            self.assertEqual(round_result(result_screen(Outcome.SUCCESS)), Outcome.SUCCESS)
            self.assertEqual(round_result(result_screen(Outcome.FAILED)), Outcome.FAILED)
            self.assertIsNone(round_result(screen_with_progress(9)))
            self.assertIsNone(round_result(screen_with_progress(12, 12)))

    def test_two_line_names_and_crossed_out_slots(self):
        screen = screen_with_progress(0)
        screen[860:870, 30:80] = 255
        screen[860:870, 380:430] = 255
        with patch("events.hidden_objects.pytesseract.image_to_string",
                   side_effect=["Espetinho\nGrelhado", "Copo de Água"]) as ocr:
            result = read_targets(screen, REGIONS)
        self.assertEqual(result, [Target(0, "Espetinho Grelhado"),
                                  Target(2, "Copo de Água")])
        self.assertEqual(ocr.call_args.kwargs["config"], "--psm 6")

    def test_two_line_english_targets_resolve_without_new_mapping(self):
        screen = screen_with_progress(0)
        screen[860:870, 30:80] = 255
        screen[860:870, 380:430] = 255
        with patch("events.hidden_objects.pytesseract.image_to_string",
                   side_effect=["Grilled\nSkewer", "Cup of\nWater"]):
            result = read_targets(screen, REGIONS)
        mapping = ObjectMap()
        self.assertEqual(mapping.coordinates("forest", result[0].name), (385, 477))
        self.assertEqual(mapping.coordinates("forest", result[1].name), (365, 575))

    def test_ocr_failure_is_explicit(self):
        screen = screen_with_progress(0)
        screen[860:870, 30:80] = 255
        with patch("events.hidden_objects.pytesseract.image_to_string", return_value=""):
            with self.assertRaisesRegex(ValueError, "slot 1"):
                read_targets(screen, REGIONS)

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.task = HiddenObjectsEvent()
        self.controller = Mock()
        self.controller.screenshot.return_value = screen_with_progress(0)

    def test_wrong_resolution_sends_no_taps(self):
        self.controller.screenshot.return_value = np.zeros((1280, 720, 3), np.uint8)
        self.assertEqual(self.task.execute(self.controller), Outcome.FAILED)
        self.controller.tap.assert_not_called()

    def test_practice_starts_with_language_independent_button_marker(self):
        screen = screen_with_progress(0)
        self.controller.screenshot.return_value = screen

        def match(image, name, *args):
            if name == "hidden_objects_success.png" or name.startswith("hidden_objects_timeout"):
                return Match(False, 0)
            if name == "hidden_objects_practice_button.png":
                return Match(False, 0)
            if name == "hidden_objects_practice_corner.png":
                return Match(True, 1, 166, 895)
            return Match(True, 1)

        with patch("events.hidden_objects.find_template", side_effect=match), \
                patch("events.hidden_objects.ContinuousCapture"), \
                patch("events.hidden_objects.ImageCandidates"), \
                patch("events.hidden_objects.RoundCapture") as live, \
                patch.object(self.task, "_solve", return_value=Outcome.SUCCESS):
            live.return_value.screenshot.return_value = screen
            self.assertEqual(self.task.execute(self.controller), Outcome.SUCCESS)
        self.controller.tap.assert_called_once_with(270, 895)

    def test_unknown_landscape_sends_no_taps(self):
        self.controller.screenshot.return_value = screen_with_progress(0)
        with patch("events.hidden_objects.find_template",
                   side_effect=lambda s, name, *args: Match(
                       name == "hidden_objects_round_marker.png", 1)):
            self.assertEqual(self.task.execute(self.controller), Outcome.FAILED)
        self.controller.tap.assert_not_called()

    def test_full_nine_block_bar_waits_for_failure_instead_of_assuming_success(self):
        mapping = ObjectMap()
        self.controller.screenshot.return_value = result_screen(Outcome.FAILED)
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.read_targets", return_value=[]), \
                patch("events.hidden_objects.remaining_seconds", return_value=60):
            result = self.task._solve(self.controller, screen_with_progress(9),
                                      "forest", mapping)
        self.assertEqual(result, Outcome.FAILED)
        self.controller.screenshot.assert_called_once()
        self.controller.tap.assert_not_called()

    def test_unknowns_queued_and_explored_without_spending_hints(self):
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.return_value = None
        self.controller.screenshot.side_effect = [
            screen_with_progress(0), screen_with_progress(0),
            screen_with_progress(0), result_screen(Outcome.FAILED)]
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.remaining_seconds", return_value=60), \
                patch.object(self.task, "_explore", return_value=None) as explore, \
                patch("events.hidden_objects.read_targets",
                      return_value=[Target(0, "New Object")]):
            result = self.task._solve(self.controller, screen_with_progress(0),
                                      "forest", mapping)
        self.assertEqual(result, Outcome.FAILED)
        mapping.queue.assert_called_once_with("forest", "New Object")
        mapping.confirm.assert_not_called()
        explore.assert_called_once()
        self.controller.tap.assert_not_called()
        self.assertEqual(self.controller.screenshot.call_count, 4)

    def test_failure_overlay_during_mapped_click_is_not_saved_as_a_hit(self):
        mapping = mock_map(reference=ObjectMap().reference)
        mapping.coordinates.return_value = (100, 200)
        self.controller.screenshot.side_effect = [
            screen_with_progress(0), result_screen(Outcome.FAILED)]
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.remaining_seconds", return_value=60), \
                patch("events.hidden_objects.read_targets", return_value=[Target(0, "Known")]):
            result = self.task._solve(self.controller, screen_with_progress(0), "forest", mapping)
        self.assertEqual(result, Outcome.FAILED)
        self.controller.tap.assert_called_once_with(100, 200)
        mapping.confirm.assert_not_called()

    def test_timer_expiry_keeps_observing_without_taps_until_failure_screen(self):
        mapping = mock_map(reference=ObjectMap().reference)
        self.controller.screenshot.return_value = result_screen(Outcome.FAILED)
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.remaining_seconds", return_value=0), \
                patch("events.hidden_objects.read_targets") as ocr:
            result = self.task._solve(self.controller, screen_with_progress(9), "forest", mapping)
        self.assertEqual(result, Outcome.FAILED)
        self.controller.screenshot.assert_called_once()
        self.controller.tap.assert_not_called()
        ocr.assert_not_called()

    def test_no_result_has_bounded_grace_and_cannot_be_assumed_success(self):
        clock = {"now": 0.0, "sequence": 0}
        capture = Mock()

        def next_frame(sequence, not_before, timeout):
            clock["now"] += min(.4, timeout)
            clock["sequence"] += 1
            return CapturedFrame(clock["sequence"], clock["now"], clock["now"],
                                 screen_with_progress(9))

        capture.next_frame.side_effect = next_frame
        live = RoundCapture(self.controller, capture)
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.remaining_seconds", return_value=0), \
                patch("events.hidden_objects.time.monotonic",
                      side_effect=lambda: clock["now"]):
            result = self.task._solve(live, screen_with_progress(9), "forest", ObjectMap())
        self.assertEqual(result, Outcome.FAILED)
        self.assertAlmostEqual(clock["now"], 5)
        self.assertEqual(live.action_deadline, 0)
        self.assertEqual(live.deadline, 5)
        self.controller.tap.assert_not_called()

    def test_candidate_failure_during_last_label_transition_stays_unconfirmed(self):
        mapping = mock_map(reference=ObjectMap().reference)
        mapping.coordinates.return_value = None
        mapping.candidates.return_value = [(72, 554)]
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        advancing = screen_with_progress(1)
        advancing[860:870, 30:80] = 255
        failed = result_screen(Outcome.FAILED)
        self.controller.screenshot.side_effect = [advancing, failed]
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.image_candidates", return_value=()):
            result = self.task._explore(self.controller, before, [Target(0, "New")],
                                        0, mapping, "forest", [], time.monotonic() + 60)
        self.assertIs(result, failed)
        self.controller.tap.assert_called_once_with(72, 554)
        mapping.confirm.assert_not_called()

    def test_existing_result_screen_is_not_dismissed_or_started_again(self):
        for outcome in (Outcome.SUCCESS, Outcome.FAILED):
            with self.subTest(outcome=outcome):
                self.controller.reset_mock()
                self.controller.screenshot.return_value = result_screen(outcome)
                with patch("events.hidden_objects.find_template", side_effect=event_match):
                    self.assertEqual(self.task.execute(self.controller), outcome)
                self.controller.tap.assert_not_called()

    def test_manual_rescue_after_exhaustion_keeps_pending_and_continues_remaining_name(self):
        for during_ocr in (False, True):
            with self.subTest(during_ocr=during_ocr), tempfile.TemporaryDirectory() as temp:
                mapping = ObjectMap(learned=Path(temp) / "memory.json")
                mapping.reference["scenes"]["forest"]["objects"] = {"Known": [120, 300]}
                before = screen_with_progress(0)
                before[860:870, 30:80] = 255
                before[860:870, 200:250] = 255
                manual = screen_with_hit(1, (159, 125))
                manual[860:870, 200:250] = 255
                both = screen_with_hit(2, (159, 125))
                both[295:306, 115:126] = 255
                frames = ([manual, manual] if during_ocr else [before, manual, manual])
                controller = Mock()
                controller.screenshot.side_effect = frames + [both, result_screen(Outcome.SUCCESS)]
                with patch("events.hidden_objects.find_template", side_effect=event_match), \
                        patch("events.hidden_objects.remaining_seconds", return_value=60), \
                        patch("events.hidden_objects.read_targets", return_value=[
                            Target(0, "New"), Target(1, "Known")]), \
                        patch.object(self.task, "_explore", return_value=None) as explore:
                    result = self.task._solve(controller, before, "forest", mapping)
                self.assertEqual(result, Outcome.SUCCESS)
                controller.tap.assert_called_once_with(120, 300)
                self.assertEqual(explore.call_count, 0 if during_ocr else 1)
                loaded = ObjectMap(learned=mapping.path)
                self.assertIsNone(loaded.coordinates("forest", "New"))
                self.assertIn("New", loaded.learned["scenes"]["forest:540x960"]["pending"])
                self.assertEqual(loaded.coordinates("forest", "Known"), (120, 300))

    def test_manual_whole_group_during_ocr_does_not_tap_cached_old_names(self):
        mapping = mock_map(reference=ObjectMap().reference)
        mapping.coordinates.side_effect = lambda scene, name: (120, 300) if name == "Known" else None
        before = screen_with_progress(0)
        replacement = screen_with_progress(3)
        for region in REGIONS:
            x, y, _, _ = region
            before[y + 5:y + 15, x + 10:x + 60] = 255
            replacement[y + 5:y + 15, x + 65:x + 115] = 255
        self.controller.screenshot.side_effect = [
            replacement, replacement, replacement, result_screen(Outcome.SUCCESS)]
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.remaining_seconds", return_value=60), \
                patch("events.hidden_objects.read_targets", side_effect=[
                    [Target(i, f"Old {i}") for i in range(3)], [Target(0, "Known")]]) as ocr:
            result = self.task._solve(self.controller, before, "forest", mapping)
        self.assertEqual(result, Outcome.SUCCESS)
        self.assertEqual(ocr.call_count, 2)
        self.controller.tap.assert_called_once_with(120, 300)
        self.assertEqual([call.args for call in mapping.queue.call_args_list],
                         [("forest", f"Old {i}") for i in range(3)])
        mapping.confirm.assert_not_called()

    def test_all_blocked_names_can_be_rescued_manually_and_next_group_resumes(self):
        mapping = mock_map(reference=ObjectMap().reference)
        mapping.coordinates.side_effect = lambda scene, name: (120, 300) if name == "Known" else None
        before = screen_with_progress(0)
        replacement = screen_with_progress(3)
        for region in REGIONS:
            x, y, _, _ = region
            before[y + 5:y + 15, x + 10:x + 60] = 255
            replacement[y + 5:y + 15, x + 65:x + 115] = 255
        self.controller.screenshot.side_effect = (
            [before] * 4 + [replacement] * 3 + [result_screen(Outcome.SUCCESS)])
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.remaining_seconds", return_value=60), \
                patch("events.hidden_objects.read_targets", side_effect=[
                    [Target(i, f"Old {i}") for i in range(3)], [Target(0, "Known")]]), \
                patch.object(self.task, "_explore", return_value=None) as explore:
            result = self.task._solve(self.controller, before, "forest", mapping)
        self.assertEqual(result, Outcome.SUCCESS)
        self.assertEqual(explore.call_count, 3)
        self.controller.tap.assert_called_once_with(120, 300)
        mapping.confirm.assert_not_called()

    def test_manual_hit_during_exploration_does_not_learn_last_guess_or_save_a_miss(self):
        clock = {"now": 0.0}
        mapping = mock_map(reference=ObjectMap().reference)
        mapping.coordinates.return_value = None
        mapping.candidates.return_value = [(120, 300), (159, 125)]
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        manual = screen_with_hit(1, (159, 125))

        def screenshot():
            clock["now"] += .3
            return manual

        self.controller.screenshot.side_effect = screenshot
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.image_candidates", return_value=()), \
                patch("events.hidden_objects.time.monotonic", side_effect=lambda: clock["now"]):
            result = self.task._explore(
                self.controller, before, [Target(0, "New")], 0, mapping, "forest", [], 60)
        self.assertIs(result, manual)
        self.controller.tap.assert_called_once_with(120, 300)
        mapping.confirm.assert_not_called()
        mapping.record_miss.assert_not_called()

    def test_another_label_crossing_near_mapped_point_cannot_confirm_requested_name(self):
        mapping = mock_map(reference=ObjectMap().reference)
        mapping.coordinates.return_value = (120, 300)
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        before[860:870, 200:250] = 255
        other = screen_with_hit(1, (120, 300))
        other[860:870, 30:80] = 255
        self.controller.screenshot.side_effect = [
            before, other, other, result_screen(Outcome.FAILED)]
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.remaining_seconds", return_value=60), \
                patch("events.hidden_objects.read_targets",
                      return_value=[Target(0, "Known"), Target(1, "Other")]):
            result = self.task._solve(self.controller, before, "forest", mapping)
        self.assertEqual(result, Outcome.FAILED)
        mapping.confirm.assert_not_called()
    def test_reconciliation_waits_for_delayed_manual_strike_without_taps(self):
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        before[860:870, 200:250] = 255
        advancing = before.copy()
        advancing[923:937] = screen_with_progress(1)[923:937]
        manual = screen_with_hit(1, (159, 125))
        manual[860:870, 200:250] = 255
        self.controller.screenshot.side_effect = [advancing, manual, manual]
        with patch("events.hidden_objects.find_template", side_effect=event_match):
            screen, remaining = self.task._reconcile_progress(
                self.controller, before, advancing,
                [Target(0, "New"), Target(1, "Known")], ObjectMap().reference,
                time.monotonic() + 60)
        self.assertIs(screen, manual)
        self.assertEqual(remaining, [Target(1, "Known")])
        self.controller.tap.assert_not_called()

    def test_verified_failed_guess_is_persisted_and_filtered_on_reload(self):
        with tempfile.TemporaryDirectory() as temp:
            mapping = ObjectMap(learned=Path(temp) / "memory.json")
            mapping.reference["scenes"]["forest"].pop("background")
            mapping.reference["scenes"]["forest"]["objects"] = {}
            mapping.reference["candidate_points"] = []
            mapping.reference["name_candidates"] = {"New": [[100, 200], [130, 300]]}
            before = screen_with_progress(0)
            before[860:870, 30:80] = 255
            clock = {"now": 0.0}

            def screenshot():
                clock["now"] += .3
                return (screen_with_hit(1, (130, 300))
                        if self.controller.tap.call_args.args == (130, 300) else before)

            self.controller.screenshot.side_effect = screenshot
            with patch("events.hidden_objects.find_template", side_effect=event_match), \
                    patch("events.hidden_objects.image_candidates", return_value=()), \
                    patch("events.hidden_objects.time.monotonic", side_effect=lambda: clock["now"]):
                result = self.task._explore(
                    self.controller, before, [Target(0, "New")], 0, mapping, "forest", [], 60)
            self.assertEqual(result[2], (130, 300))
            loaded = ObjectMap(learned=mapping.path)
            self.assertTrue(loaded.was_missed("forest", "New", (100, 200)))
            self.assertFalse(loaded.was_missed("forest", "Other", (100, 200)))
            loaded.reference = mapping.reference
            self.controller.reset_mock()
            self.controller.screenshot.return_value = screen_with_hit(1, (130, 300))
            with patch("events.hidden_objects.find_template", side_effect=event_match), \
                    patch("events.hidden_objects.image_candidates", return_value=()):
                self.task._explore(self.controller, before, [Target(0, "New")], 0,
                                   loaded, "forest", [], time.monotonic() + 60)
            self.controller.tap.assert_called_once_with(130, 300)

    def test_shortened_confirmation_window_does_not_persist_a_false_miss(self):
        mapping = mock_map(reference=ObjectMap().reference)
        mapping.coordinates.return_value = None
        mapping.candidates.return_value = [(100, 200)]
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        clock = {"now": 0.0}

        def screenshot():
            clock["now"] += .3
            return before

        self.controller.screenshot.side_effect = screenshot
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.image_candidates", return_value=()), \
                patch("events.hidden_objects.time.monotonic", side_effect=lambda: clock["now"]):
            self.task._explore(
                self.controller, before, [Target(0, "New")], 0, mapping, "forest", [], 1)
        mapping.record_miss.assert_not_called()

    def test_cooldown_overlay_interrupts_exploration_without_saving_a_miss(self):
        mapping = mock_map(reference=ObjectMap().reference)
        mapping.coordinates.return_value = None
        mapping.candidates.return_value = [(100, 200)]
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        overlay = screen_with_progress(0)
        overlay[0, 0, 0] = 3
        self.controller.screenshot.return_value = overlay

        def match(screen, name, *args):
            if screen[0, 0, 0] == 3:
                return Match(False, 0)
            return event_match(screen, name, *args)

        with patch("events.hidden_objects.find_template", side_effect=match), \
                patch("events.hidden_objects.image_candidates", return_value=()):
            result = self.task._explore(self.controller, before, [Target(0, "New")],
                                        0, mapping, "forest", [], time.monotonic() + 60)
        self.assertIs(result, overlay)
        mapping.record_miss.assert_not_called()

    def test_round_capture_cannot_tap_during_result_grace(self):
        live = RoundCapture(self.controller, Mock())
        live.action_deadline = 10
        live.deadline = 15
        with patch("events.hidden_objects.time.monotonic", return_value=11), \
                self.assertRaises(TimeoutError):
            live.tap(100, 200)
        self.controller.tap.assert_not_called()

    def test_exploration_records_actual_crossed_name_not_intended_guess(self):
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.return_value = None
        mapping.candidates.return_value = [(159, 125)]
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        before[860:870, 200:250] = 255
        after = screen_with_hit(1, (159, 125))
        after[860:870, 30:80] = 255
        self.controller.screenshot.return_value = after
        targets = [Target(0, "Unknown One"), Target(1, "Unknown Two")]
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.time.monotonic", return_value=0), \
                patch("events.hidden_objects.time.sleep"):
            result = self.task._explore(self.controller, before, targets, 0,
                                        mapping, "forest", [], 60)
        self.assertEqual(result[1], targets[1])
        self.assertEqual(result[2], (159, 125))
        self.controller.tap.assert_called_once_with(159, 125)

    def test_exploration_excludes_other_requested_and_found_objects(self):
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.return_value = (100, 200)
        mapping.candidates.return_value = [(100, 200), (150, 300)]
        result = self.task._explore(self.controller, screen_with_progress(0),
                                    [Target(0, "Unknown"), Target(1, "Known")],
                                    0, mapping, "forest", [(150, 300)], 60)
        self.assertIsNone(result)
        self.controller.tap.assert_not_called()

    def test_exploration_waits_for_delayed_strike_through_without_extra_taps(self):
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.return_value = None
        mapping.candidates.return_value = [(72, 554)]
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        advancing = screen_with_progress(1)
        advancing[860:870, 30:80] = 255
        self.controller.screenshot.side_effect = [
            advancing, advancing, screen_with_hit(1, (72, 554))]
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.time.monotonic", return_value=0), \
                patch("events.hidden_objects.time.sleep"):
            result = self.task._explore(
                self.controller, before, [Target(0, "Muleta")], 0,
                mapping, "forest", [], 60)
        self.assertEqual(result[1], Target(0, "Muleta"))
        self.controller.tap.assert_called_once_with(72, 554)

    def test_delayed_candidate_hit_is_not_attributed_to_next_location(self):
        clock = {"now": 0.0}
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.return_value = None
        mapping.candidates.return_value = [(72, 554), (159, 125)]
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255

        def screenshot():
            clock["now"] += .2
            return screen_with_hit(1, (72, 554)) if clock["now"] >= .8 else before

        self.controller.screenshot.side_effect = screenshot
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.time.monotonic",
                      side_effect=lambda: clock["now"]):
            result = self.task._explore(
                self.controller, before, [Target(0, "Muleta")], 0,
                mapping, "forest", [], 60)
        self.assertEqual(result[2], (72, 554))
        self.controller.tap.assert_called_once_with(72, 554)

    def test_empty_map_uses_image_proposals_and_confirms_actual_hit(self):
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.return_value = None
        mapping.candidates.return_value = []
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        self.controller.screenshot.return_value = screen_with_hit(1, (120, 300))
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.image_candidates",
                      return_value=(Proposal((120, 300), 20),)):
            result = self.task._explore(self.controller, before, [Target(0, "New")],
                                        0, mapping, "forest", [], 60)
        self.assertEqual(result[1:], (Target(0, "New"), (120, 300)))
        self.controller.tap.assert_called_once_with(120, 300)

    def test_live_exploration_uses_fresh_parallel_analysis_not_sync_detector(self):
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.return_value = None
        mapping.candidates.return_value = []
        capture = Mock()
        capture.next_frame.return_value = CapturedFrame(
            8, 1, 1.1, screen_with_hit(1, (120, 300)))
        live = RoundCapture(self.controller, capture)
        live.sequence = 7
        live.candidates = Mock()
        live.candidates.latest.return_value = CandidateFrame(
            7, 0, (Proposal((120, 300), 20),))
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.image_candidates") as sync:
            result = self.task._explore(live, screen_with_progress(0), [Target(0, "New")],
                                        0, mapping, "forest", [], time.monotonic() + 60)
        sync.assert_not_called()
        self.assertEqual(live.candidates.latest.call_args.args[:2], (7, 0))
        self.assertEqual(result[2], (120, 300))

    def test_clean_background_uses_only_present_visual_candidates(self):
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.return_value = None
        mapping.background.return_value = np.zeros((735, 450, 3), np.uint8)
        mapping.candidates.return_value = [(100, 200)]
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        self.controller.screenshot.return_value = screen_with_hit(1, (120, 300))
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.image_candidates",
                      return_value=(Proposal((120, 300), 20),)) as detector:
            result = self.task._explore(self.controller, before, [Target(0, "New")],
                                        0, mapping, "forest", [], 60)
        self.assertEqual(result[2], (120, 300))
        self.controller.tap.assert_called_once_with(120, 300)
        mapping.candidates.assert_not_called()
        self.assertIs(detector.call_args.args[2], mapping.background.return_value)

    def test_clean_background_still_filters_item_specific_misses(self):
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.return_value = None
        mapping.background.return_value = np.zeros((735, 450, 3), np.uint8)
        mapping.was_missed.side_effect = lambda scene, name, point: point == (100, 200)
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        self.controller.screenshot.return_value = screen_with_hit(1, (120, 300))
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.image_candidates",
                      return_value=(Proposal((100, 200), 30), Proposal((120, 300), 20))):
            result = self.task._explore(self.controller, before, [Target(0, "New")],
                                        0, mapping, "forest", [], 60)
        self.assertEqual(result[2], (120, 300))
        self.controller.tap.assert_called_once_with(120, 300)

    def test_attempts_are_shared_between_targets_of_same_group(self):
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.return_value = None
        mapping.candidates.return_value = [(100, 200)]
        with patch("events.hidden_objects.image_candidates", return_value=()):
            result = self.task._explore(
                self.controller, screen_with_progress(0), [Target(0, "New")],
                0, mapping, "forest", [], 60, [(100, 200)])
        self.assertIsNone(result)
        self.controller.tap.assert_not_called()

    def test_saved_candidates_cannot_starve_image_candidates(self):
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.return_value = None
        mapping.candidates.return_value = [(100 + 20 * i, 200) for i in range(15)]
        clock = {"now": 0}
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255

        def screenshot():
            clock["now"] += .2
            point = self.controller.tap.call_args.args
            return screen_with_hit(1, (120, 300)) if point == (120, 300) else before

        self.controller.screenshot.side_effect = screenshot
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.image_candidates",
                      return_value=(Proposal((120, 300), 20),)), \
                patch("events.hidden_objects.time.monotonic",
                      side_effect=lambda: clock["now"]):
            result = self.task._explore(
                self.controller, before, [Target(0, "New")], 0,
                mapping, "forest", [], 60)
        self.assertEqual(result[2], (120, 300))
        self.assertEqual([call.args for call in self.controller.tap.call_args_list],
                         [(100, 200), (120, 300)])

    def test_round_capture_surfaces_analysis_failure_even_for_mapped_targets(self):
        live = RoundCapture(self.controller, Mock())
        live.candidates = Mock()
        live.candidates.raise_if_failed.side_effect = RuntimeError("analysis failed")
        with self.assertRaisesRegex(RuntimeError, "analysis failed"):
            live.screenshot()
        live.capture.next_frame.assert_not_called()

    def test_solver_prioritizes_first_label_even_when_later_label_is_mapped(self):
        mapping = mock_map()
        mapping.reference = ObjectMap().reference
        mapping.coordinates.side_effect = lambda scene, name: (
            (151, 514) if name == "Bússola" else None)
        targets = [Target(0, "Unknown"), Target(1, "Bússola")]
        self.controller.screenshot.side_effect = [
            screen_with_progress(0), result_screen(Outcome.FAILED)]
        with patch("events.hidden_objects.find_template", side_effect=event_match), \
                patch("events.hidden_objects.remaining_seconds", return_value=60), \
                patch("events.hidden_objects.read_targets", return_value=targets), \
                patch.object(self.task, "_explore", return_value=None) as explore:
            self.task._solve(self.controller, screen_with_progress(0),
                             "forest", mapping)
        self.assertEqual(explore.call_args.args[2][0], targets[0])
        self.controller.tap.assert_not_called()

    def test_progress_without_label_change_is_not_confirmed(self):
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        after = screen_with_progress(1)
        after[860:870, 30:80] = 255
        self.controller.screenshot.return_value = after
        with patch("events.hidden_objects.time.monotonic",
                   side_effect=[0, 0, 3]), patch("events.hidden_objects.time.sleep"):
            self.assertIsNone(self.task._wait_confirmation(
                self.controller, before, Target(0, "Test"), 0,
                ObjectMap().reference, 60))

    def test_crossed_label_and_progress_confirms_click(self):
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        self.controller.screenshot.return_value = screen_with_progress(1)
        with patch("events.hidden_objects.time.monotonic", return_value=0), \
                patch("events.hidden_objects.time.sleep"):
            self.assertIsNotNone(self.task._wait_confirmation(
                self.controller, before, Target(0, "Test"), 0,
                ObjectMap().reference, 60))

    def test_variable_rounds_read_each_group_once_and_wait_for_success_screen(self):
        event = HiddenObjectsEvent()
        reference = ObjectMap().reference
        for total in (9, 10, 11, 12, 15, 18):
            with self.subTest(total=total):
                state = {"count": 0, "complete_frames": 0}

                def screen():
                    count = state["count"]
                    if count == total:
                        state["complete_frames"] += 1
                        if state["complete_frames"] >= 3:
                            return result_screen(Outcome.SUCCESS)
                    image = screen_with_progress(count, total)
                    image[195:206, 95:106] = 255 if count % 2 else 40
                    for slot, region in enumerate(REGIONS):
                        if (count == total or slot < count % 3
                                or slot >= min(3, total - 3 * (count // 3))):
                            continue
                        x1, y1, _, _ = region
                        shift = 15 * (count // 3)
                        image[y1 + 5:y1 + 15, x1 + 10 + shift:x1 + 60 + shift] = 255
                    return image

                controller = Mock()
                controller.screenshot.side_effect = screen
                controller.tap.side_effect = lambda x, y: state.update(count=state["count"] + 1)
                mapping = mock_map(reference=reference)
                mapping.coordinates.return_value = (100, 200)
                groups = [[Target(i, f"Group {g} Object {i}")
                           for i in range(min(3, total - 3 * g))]
                          for g in range((total + 2) // 3)]
                with patch("events.hidden_objects.find_template", side_effect=event_match), \
                        patch("events.hidden_objects.remaining_seconds", return_value=60), \
                        patch("events.hidden_objects.read_targets", side_effect=groups) as ocr, \
                        patch("events.hidden_objects.time.sleep") as sleep:
                    result = event._solve(controller, screen(), "forest", mapping)
                self.assertEqual(result, Outcome.SUCCESS)
                self.assertEqual(ocr.call_count, (total + 2) // 3)
                self.assertEqual(controller.tap.call_count, total)
                self.assertEqual(mapping.confirm.call_count, total)
                self.assertGreaterEqual(state["complete_frames"], 3)
                sleep.assert_not_called()

    def test_unrelated_label_change_cannot_confirm_nonfinal_click(self):
        before = screen_with_progress(0)
        before[860:870, 30:80] = 255
        after = screen_with_progress(1)
        after[860:875, 30:100] = 255
        self.controller.screenshot.return_value = after
        with patch("events.hidden_objects.time.monotonic", side_effect=[0, 0, 3]):
            self.assertIsNone(self.task._wait_confirmation(
                self.controller, before, Target(0, "Test"), 0,
                ObjectMap().reference, 60))

    def test_round_capture_excludes_frames_started_before_tap_completed(self):
        controller = Mock()
        capture = Mock()
        frame = CapturedFrame(7, 11, 11.1, screen_with_progress(0))
        capture.next_frame.return_value = frame
        live = RoundCapture(controller, capture)
        with patch("events.hidden_objects.time.monotonic",
                   side_effect=[10, 10.2, 10.5, 11, 11.1]):
            live.tap(100, 200)
            self.assertIs(live.screenshot(), frame.image)
        self.assertEqual(capture.next_frame.call_args.args[:2], (-1, 10.5))
        self.assertEqual(live.sequence, 7)
        self.assertEqual(live.taps, 1)

    def test_round_capture_does_not_tap_after_deadline(self):
        controller = Mock()
        live = RoundCapture(controller, Mock())
        live.deadline = 10
        with patch("events.hidden_objects.time.monotonic", return_value=10), \
                self.assertRaises(TimeoutError):
            live.tap(100, 200)
        controller.tap.assert_not_called()

    def test_round_capture_rejects_resolution_change(self):
        capture = Mock()
        capture.next_frame.side_effect = [
            CapturedFrame(1, 0, 0, screen_with_progress(0)),
            CapturedFrame(2, 1, 1, np.zeros((1280, 720, 3), np.uint8)),
        ]
        live = RoundCapture(Mock(), capture)
        live.screenshot()
        with self.assertRaisesRegex(RuntimeError, "resolution changed"):
            live.screenshot()

    def test_capture_worker_closes_when_solver_raises(self):
        controller = Mock()
        controller.screenshot.return_value = screen_with_progress(0)
        event = HiddenObjectsEvent()
        with patch("events.hidden_objects.find_template",
                   side_effect=lambda s, name, *args: Match(
                       name in ("hidden_objects_round_marker.png",
                                "hidden_objects_forest_scene.png"), 1)), \
                patch("events.hidden_objects.ContinuousCapture") as capture, \
                patch("events.hidden_objects.ImageCandidates") as candidates, \
                patch.object(event, "_solve", side_effect=ValueError("bad OCR")):
            capture.return_value.started_at = 0
            capture.return_value.stopped_at = 1
            capture.return_value.capture_seconds = .1
            capture.return_value.frames = 1
            capture.return_value.next_frame.return_value = CapturedFrame(
                1, 0, 0, screen_with_progress(0))
            candidates.return_value.__enter__.return_value.frames = 0
            candidates.return_value.__enter__.return_value.analysis_seconds = 0
            with self.assertRaisesRegex(ValueError, "bad OCR"):
                event.execute(controller)
        capture.return_value.__exit__.assert_called_once()
        candidates.return_value.__exit__.assert_called_once()

    def test_frame_timeout_returns_failure_not_success(self):
        controller = Mock()
        controller.screenshot.return_value = screen_with_progress(0)
        event = HiddenObjectsEvent()
        with patch("events.hidden_objects.find_template",
                   side_effect=lambda s, name, *args: Match(
                       name in ("hidden_objects_round_marker.png",
                                "hidden_objects_forest_scene.png"), 1)), \
                patch("events.hidden_objects.ContinuousCapture") as capture:
            capture.return_value.started_at = 0
            capture.return_value.stopped_at = 1
            capture.return_value.capture_seconds = 0
            capture.return_value.frames = 0
            capture.return_value.next_frame.side_effect = TimeoutError("no fresh frame")
            self.assertEqual(event.execute(controller), Outcome.FAILED)
        capture.return_value.__exit__.assert_called_once()


class IntegrationTests(unittest.TestCase):
    def test_all_events_excluded_from_daily_tasks(self):
        for event in EVENTS.values():
            self.assertNotIn(event, TASKS)
            self.assertNotIn(event.name, [task.name for task in TASKS])
        with patch("main.sys.stdin") as stdin:
            stdin.isatty.return_value = False
            self.assertEqual(main.select_active_tasks(
                TASKS, list(EVENTS.values())), TASKS)

    def test_events_have_their_own_submenu(self):
        with patch("main.sys.stdin") as stdin, \
                patch("main.console.timed_input", side_effect=["3", "1"]):
            stdin.isatty.return_value = True
            self.assertEqual(main.select_active_tasks(
                TASKS, list(EVENTS.values())),
                [EVENTS["hidden-objects"]])

    def test_individual_execution_preserves_prepared_screen_and_exits_once(self):
        task = Mock(requires_profile=False)
        task.execute.return_value = Outcome.SUCCESS
        with patch.dict(main.EVENTS, {"test": task}, clear=True), \
                patch("main.ensure_game_ready"), \
                patch("main.go_to_home_screen") as home, \
                patch("main.read_player_profile") as profile, \
                patch("main.check_task") as daily:
            controller = Mock(port=5555)
            main.run_loop(controller, event=task)
        task.execute.assert_called_once_with(controller)
        home.assert_not_called()
        profile.assert_not_called()
        daily.assert_not_called()

    def test_canceling_event_menu_does_not_fall_back_to_daily_tasks(self):
        with patch("main.sys.stdin") as stdin, \
                patch("main.console.timed_input", side_effect=["3", ""]):
            stdin.isatty.return_value = True
            self.assertEqual(main.select_active_tasks(TASKS, list(EVENTS.values())), [])

    def test_castle_event_reads_profile_without_scheduling_daily_tasks(self):
        event = Mock(requires_profile=True)
        event.execute.return_value = Outcome.SUCCESS
        with patch.dict(main.EVENTS, {"castle-battle": event}, clear=True), \
                patch("main.ensure_game_ready"), \
                patch("main.go_to_home_screen", return_value=True) as home, \
                patch("main.read_player_profile") as profile, \
                patch("main.check_task") as daily:
            controller = Mock(port=5555)
            main.run_loop(controller, event=event)
        event.execute.assert_called_once_with(controller)
        home.assert_called_once_with(controller)
        profile.assert_called_once_with(controller)
        daily.assert_not_called()

    def test_daily_single_task_menu_does_not_include_events(self):
        with patch("main.sys.stdin") as stdin, \
                patch("main.console.timed_input", side_effect=["2", "1"]):
            stdin.isatty.return_value = True
            self.assertEqual(main.select_active_tasks(
                TASKS, list(EVENTS.values())), [TASKS[0]])

    def test_task_menu_timeout_preserves_default_daily_execution(self):
        with patch("main.sys.stdin") as stdin, \
                patch("main.console.timed_input", return_value=None):
            stdin.isatty.return_value = True
            self.assertEqual(main.select_active_tasks(
                TASKS, list(EVENTS.values())), TASKS)

    def test_cli_task_selection_preserves_panel_control(self):
        with patch("main.sys.argv", ["main.py", "--port", "5555",
                                    "--task", TASKS[0].name, "--control-stdin"]), \
                patch("main.bot_control.listen_stdin") as listen, \
                patch("main.ADBController") as controller, \
                patch("main.run_loop") as run:
            main.main()
        listen.assert_called_once()
        run.assert_called_once_with(controller.return_value, [TASKS[0]], event=None)

    def test_cli_event_selection_preserves_panel_control(self):
        with patch("main.sys.argv", ["main.py", "--port", "5555",
                                    "--event", "hidden-objects", "--control-stdin"]), \
                patch("main.bot_control.listen_stdin") as listen, \
                patch("main.ADBController") as controller, \
                patch("main.run_loop") as run:
            main.main()
        listen.assert_called_once()
        run.assert_called_once_with(
            controller.return_value, None, event=EVENTS["hidden-objects"])

    def test_cli_rejects_mixing_daily_task_and_event(self):
        with patch("main.sys.argv", ["main.py", "--task", TASKS[0].name,
                                    "--event", "hidden-objects"]), \
                patch("main.sys.stderr"), \
                self.assertRaises(SystemExit) as stopped:
            main.parse_args()
        self.assertEqual(stopped.exception.code, 2)

    def test_selected_daily_task_bypasses_menu_and_event_execution(self):
        task = Mock(loop=False)
        task.name = "Daily task"
        controller = Mock(port=5555)
        with patch("main.select_active_tasks") as menu, \
                patch("main.ensure_game_ready"), \
                patch("main.go_to_home_screen"), \
                patch("main.read_player_profile"), \
                patch("main.order_tasks", return_value=[task]), \
                patch("main.account_prefs.disabled_tasks", return_value=[]), \
                patch("main.check_task", side_effect=KeyboardInterrupt) as daily:
            main.run_loop(controller, [task])
        menu.assert_not_called()
        self.assertEqual(daily.call_args.args[:3], (controller, 5555, task))
        task.execute.assert_not_called()


class CastleBattleTests(unittest.TestCase):
    def test_relocated_castle_preserves_infirmary_limits(self):
        event = CastleBattleEvent()
        with patch("events.castle_battle.config.CASTLE_INJURED_LIMIT", 20000), \
                patch("events.castle_battle.config.CASTLE_INFIRMARY_PCT_LIMIT", 50):
            self.assertFalse(event._over_limit(10000, 100000))
            self.assertTrue(event._over_limit(20000, 100000))
            self.assertTrue(event._over_limit(15000, 30000))

    def test_wrong_castle_modal_never_launches_an_attack(self):
        event = CastleBattleEvent()
        controller = Mock()
        with patch.object(event, "_tap", return_value=True) as tap, \
                patch("events.castle_battle.find_template", return_value=Match(False, 0)), \
                patch("events.castle_battle.time.sleep"):
            self.assertIsNone(event._attack_castle(controller))
        self.assertEqual(tap.call_count, 3)
        controller.back.assert_called_once()

    def test_castle_heal_selection_still_zeros_other_troop_types(self):
        event = CastleBattleEvent()
        rows = [("infantry", 1000, 100), ("cavalry", 1500, 200),
                ("archer", 2000, 300)]
        controller = Mock()
        with patch.object(event, "_set_quantity", return_value=True) as quantity, \
                patch("events.castle_battle.config.HEAL_QTY_BOX_DY", 20):
            self.assertTrue(event._select_only(controller, rows, rows[1], 200))
        self.assertEqual([call.args[2] for call in quantity.call_args_list], [0, 200, 0])


if __name__ == "__main__":
    unittest.main()
