import json
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from events.fishing_catalog import parse_catalog, plan_collection
from events.fishing_tournament import (
    EVENT_TABS, is_fishing_paused, is_tab_selected, open_event_tab,
    read_fishing_hud, read_handbook_card, reset_fishing_round,
    retreat_paused_round, start_trial_stage,
)


def specimen(identifier=10001, **overrides):
    return {
        "id": identifier, "name": "Rosy Bitterling", "category": "Catches",
        "star": 1, "points": 10, "sellPrice": 10, "depth": 10,
        "seasons": [2, 4], "image": "/images/tools/fishing-handbook/rosy-bitterling.webp",
        **overrides,
    }


class FishingCatalogTests(unittest.TestCase):
    def test_trial_start_never_taps_unrecognized_entry(self):
        controller = Mock()
        with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                patch("events.fishing_tournament.is_event_screen", return_value=False), \
                patch("events.fishing_tournament.is_trial_entry", return_value=False):
            capture.return_value.__enter__.return_value.next_frame.return_value = Mock(image=Mock())
            with self.assertRaisesRegex(RuntimeError, "no start tap sent"):
                start_trial_stage(controller)
        controller.tap.assert_not_called()

    def test_trial_start_waits_for_countdown_and_active_trial_hud(self):
        controller = Mock(serial="127.0.0.1:5555")
        frames = [Mock(image=Mock(), sequence=1, completed_at=100),
                  Mock(image=Mock(), sequence=2, completed_at=101),
                  Mock(image=Mock(), sequence=3, completed_at=102),
                  Mock(image=Mock(), sequence=4, completed_at=104)]
        hud = {"captured": 0, "capacity": 10, "depth": 1, "max_depth": 100}
        with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                patch("events.fishing_tournament.is_event_screen", return_value=False), \
                patch("events.fishing_tournament.is_trial_entry", return_value=True), \
                patch("events.fishing_tournament.read_white_text", side_effect=["3", "2", "1"]), \
                patch("events.fishing_tournament.has_pause_icon", return_value=True), \
                patch("events.fishing_tournament.read_fishing_hud", return_value=hud), \
                patch("events.fishing_tournament.time.monotonic", return_value=100):
            capture.return_value.__enter__.return_value.next_frame.side_effect = frames
            report = start_trial_stage(controller)
        controller.tap.assert_called_once_with(270, 835)
        self.assertEqual(report["observed_countdown"], ["3", "2", "1"])
        self.assertEqual(report["start_elapsed_seconds"], 4)

    def test_reset_only_taps_pause_then_retreat_after_confirmation(self):
        controller = Mock()
        with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                patch("events.fishing_tournament.is_fishing_paused", side_effect=[False, True]), \
                patch("events.fishing_tournament.has_pause_icon", return_value=True), \
                patch("events.fishing_tournament.read_fishing_hud", return_value={"depth": 1}), \
                patch("events.fishing_tournament.is_event_screen", return_value=True), \
                patch("events.fishing_tournament.is_tab_selected", return_value=True):
            capture.return_value.__enter__.return_value.next_frame.return_value = Mock(image=Mock())
            reset_fishing_round(controller)
        self.assertEqual([call.args for call in controller.tap.call_args_list], [(510, 26), (192, 480)])

    def test_reset_rejects_unrecognized_round(self):
        controller = Mock()
        with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                patch("events.fishing_tournament.is_fishing_paused", return_value=False), \
                patch("events.fishing_tournament.has_pause_icon", return_value=False):
            capture.return_value.__enter__.return_value.next_frame.return_value = Mock(image=Mock())
            with self.assertRaisesRegex(RuntimeError, "no Pause tap sent"):
                reset_fishing_round(controller)
        controller.tap.assert_not_called()

    def test_reset_from_pause_does_not_tap_pause_again(self):
        controller = Mock()
        with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                patch("events.fishing_tournament.is_fishing_paused", return_value=True), \
                patch("events.fishing_tournament.is_event_screen", return_value=True), \
                patch("events.fishing_tournament.is_tab_selected", return_value=True):
            capture.return_value.__enter__.return_value.next_frame.return_value = Mock(image=Mock())
            reset_fishing_round(controller)
        controller.tap.assert_called_once_with(192, 480)

    def test_reset_does_not_retreat_when_pause_confirmation_times_out(self):
        controller = Mock()
        with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                patch("events.fishing_tournament.is_fishing_paused", return_value=False), \
                patch("events.fishing_tournament.has_pause_icon", return_value=True), \
                patch("events.fishing_tournament.read_fishing_hud", return_value={"depth": 1}), \
                patch("events.fishing_tournament.time.monotonic", side_effect=[0, 2]):
            capture.return_value.__enter__.return_value.next_frame.return_value = Mock(image=Mock())
            with self.assertRaisesRegex(RuntimeError, "no Retreat tap sent"):
                reset_fishing_round(controller, timeout=1)
        controller.tap.assert_called_once_with(510, 26)

    def test_fishing_hud_rejects_invalid_fractions(self):
        image = np.zeros((960, 540, 3), np.uint8)
        with patch("events.fishing_tournament.read_white_text", side_effect=["0/10", "1/100"]):
            self.assertEqual(read_fishing_hud(image),
                             {"captured": 0, "capacity": 10, "depth": 1, "max_depth": 100})
        with patch("events.fishing_tournament.read_white_text", return_value="11/10"):
            self.assertIsNone(read_fishing_hud(image))

    def test_pause_menu_requires_both_labels(self):
        image = np.zeros((960, 540, 3), np.uint8)
        with patch("events.fishing_tournament.read_white_text", side_effect=["Retreat", "Continue"]):
            self.assertTrue(is_fishing_paused(image))
        with patch("events.fishing_tournament.read_white_text", side_effect=["Retreat", "Unknown"]):
            self.assertFalse(is_fishing_paused(image))

    def test_retreat_requires_confirmed_pause_menu(self):
        controller = Mock()
        with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                patch("events.fishing_tournament.is_fishing_paused", return_value=False):
            capture.return_value.__enter__.return_value.next_frame.return_value = Mock(image=Mock())
            with self.assertRaisesRegex(RuntimeError, "no Retreat tap sent"):
                retreat_paused_round(controller)
        controller.tap.assert_not_called()

    def test_retreat_is_sent_once_and_checks_return(self):
        controller = Mock()
        with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                patch("events.fishing_tournament.is_fishing_paused", side_effect=[True, False]):
            capture.return_value.__enter__.return_value.next_frame.return_value = Mock(image=Mock())
            retreat_paused_round(controller)
        controller.tap.assert_called_once_with(192, 480)

    def test_selected_tab_uses_white_background_not_label(self):
        for tab, target in EVENT_TABS.items():
            image = np.zeros((960, 540, 3), np.uint8)
            center_x, _ = target["tap"]
            image[88:132, center_x - 65:center_x + 65] = 245
            image[88:132, center_x - 50:center_x + 50] = 0
            self.assertTrue(is_tab_selected(image, tab))
            self.assertFalse(is_tab_selected(np.zeros_like(image), tab))

    def test_tab_navigation_rejects_other_screens_without_actions(self):
        controller = Mock()
        frame = Mock(image=np.zeros((960, 540, 3), np.uint8))
        with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                patch("events.fishing_tournament.is_event_screen", return_value=False):
            capture.return_value.__enter__.return_value.next_frame.return_value = frame
            with self.assertRaisesRegex(RuntimeError, "no modal"):
                open_event_tab(controller, "handbook")
        controller.tap.assert_not_called()
        controller.swipe.assert_not_called()

    def test_tab_navigation_stops_after_unconfirmed_selection(self):
        controller = Mock()
        frame = Mock(image=np.zeros((960, 540, 3), np.uint8))
        with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                patch("events.fishing_tournament.is_event_screen", return_value=True):
            capture.return_value.__enter__.return_value.next_frame.return_value = frame
            with self.assertRaisesRegex(RuntimeError, "Could not confirm"):
                open_event_tab(controller, "handbook")
        controller.tap.assert_called_once_with(438, 105)
        controller.swipe.assert_called_once_with(450, 130, 90, 130, duration_ms=700)

    def test_tab_navigation_does_not_tap_when_event_changes_after_scroll(self):
        controller = Mock()
        frame = Mock(image=np.zeros((960, 540, 3), np.uint8))
        with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                patch("events.fishing_tournament.is_event_screen", side_effect=[True, False]):
            capture.return_value.__enter__.return_value.next_frame.return_value = frame
            with self.assertRaisesRegex(RuntimeError, "no tab tap sent"):
                open_event_tab(controller, "handbook")
        controller.tap.assert_not_called()

    def test_tab_navigation_aligns_before_tapping_and_verifies_selection(self):
        for tab, target in EVENT_TABS.items():
            controller = Mock()
            image = np.zeros((960, 540, 3), np.uint8)
            center_x, _ = target["tap"]
            image[88:132, center_x - 65:center_x + 65] = 245
            with patch("events.fishing_tournament.ContinuousCapture") as capture, \
                    patch("events.fishing_tournament.is_event_screen", return_value=True):
                capture.return_value.__enter__.return_value.next_frame.return_value = Mock(image=image)
                open_event_tab(controller, tab)
            swipe = ((90, 130, 450, 130) if target["edge"] == "left" else (450, 130, 90, 130))
            controller.swipe.assert_called_once_with(*swipe, duration_ms=700)
            controller.tap.assert_called_once_with(*target["tap"])
            self.assertEqual([call[0] for call in controller.method_calls], ["swipe", "tap"])

    def test_card_reader_rejects_other_screens(self):
        self.assertIsNone(read_handbook_card(np.zeros((960, 540, 3), np.uint8), [specimen()]))

    def test_card_reader_matches_name_and_capture_badge(self):
        image = np.zeros((960, 540, 3), np.uint8)
        image[320:335, 160:400] = (180, 220, 240)
        image[383:410, 365:402] = (0, 180, 0)
        with patch("events.fishing_tournament.pytesseract.image_to_string", return_value="Rosy Bitterling"):
            card = read_handbook_card(image, [specimen()])
        self.assertTrue(card["captured"])
        self.assertEqual(card["id"], 10001)
        self.assertEqual(card["points"], 10)

    def test_card_reader_does_not_guess_unreadable_names(self):
        image = np.zeros((960, 540, 3), np.uint8)
        image[320:335, 160:400] = (180, 220, 240)
        with patch("events.fishing_tournament.pytesseract.image_to_string", return_value="???"):
            self.assertIsNone(read_handbook_card(image, [specimen()]))

    def test_missing_requires_gray_stars_and_silhouette(self):
        image = np.zeros((960, 540, 3), np.uint8)
        image[320:335, 160:400] = (180, 220, 240)
        with patch("events.fishing_tournament.pytesseract.image_to_string", return_value="Rosy Bitterling"):
            self.assertIsNone(read_handbook_card(image, [specimen()])["captured"])
            image[375:390, 240:300] = (150, 145, 115)
            image[450:510, 220:320] = (140, 160, 164)
            self.assertFalse(read_handbook_card(image, [specimen()])["captured"])

    def test_parse_json_and_embedded_dataset(self):
        entries = [specimen(name='"Roman\'s Log"')]
        source = json.dumps(entries)
        self.assertEqual(parse_catalog(source), entries)
        escaped = source.replace("\\", "\\\\").replace("'", "\\'")
        embedded = "module(JSON.parse('" + escaped + "'))"
        self.assertEqual(parse_catalog(embedded), entries)

    def test_autumn_uses_source_season_number_four(self):
        entries = [specimen(1, seasons=[3]), specimen(2, seasons=[4])]
        self.assertEqual([entry["id"] for entry in
                          plan_collection(entries, {}, "autumn", 250)], [2])

    def test_summer_fish_is_saved_but_not_targeted_in_winter(self):
        entries = [specimen(1, seasons=[3]), specimen(2, seasons=[1])]
        states = {"1": {"captured": False}, "2": {"captured": False}}
        planned = plan_collection(entries, states, "winter", 250, include_unavailable=True)
        self.assertEqual([entry["id"] for entry in planned], [2, 1])
        summer_fish = planned[1]
        self.assertEqual(summer_fish["available_seasons"], ["summer"])
        self.assertEqual(summer_fish["event_season"], "winter")
        self.assertEqual(summer_fish["awaiting_seasons"], ["summer"])
        self.assertFalse(summer_fish["available_now"])
        self.assertFalse(summer_fish["eligible_now"])
        self.assertEqual(summer_fish["capture_status"], "missing")

    def test_special_entries_preserve_unknown_points(self):
        entries = [specimen(category="Mermaids", star=None, points=None)]
        self.assertEqual(parse_catalog(json.dumps(entries)), entries)
        planned = plan_collection(entries, {}, "autumn", 250)
        self.assertIsNone(planned[0]["points"])
        self.assertEqual(planned[0]["sellPrice"], 10)

    def test_unknown_is_not_missing_or_captured(self):
        planned = plan_collection([specimen()], {}, "autumn", 250)
        self.assertEqual(planned[0]["capture_status"], "unknown")
        self.assertTrue(planned[0]["reachable"])
        self.assertTrue(planned[0]["image_url"].startswith("https://kingshotmastery.com/"))

    def test_prioritize_reachable_missing_before_points(self):
        entries = [specimen(1, points=150), specimen(2, points=20),
                   specimen(3, points=150, depth=400), specimen(4, seasons=[1])]
        states = {"1": {"captured": True}, "2": {"captured": False},
                  "3": {"captured": False}}
        planned = plan_collection(entries, states, "autumn", 250)
        self.assertEqual([entry["id"] for entry in planned], [2, 1, 3])
        self.assertFalse(planned[-1]["reachable"])

    def test_invalid_data_is_rejected(self):
        for entries in ([], [specimen(), specimen()], [specimen(points=-1)],
                        [specimen(category="Other")], [specimen(seasons=[5])]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                parse_catalog(json.dumps(entries))
        with self.assertRaises(ValueError):
            plan_collection([specimen()], {"10001": {"captured": "false"}}, "autumn", 250)


if __name__ == "__main__":
    unittest.main()