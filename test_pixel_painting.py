import queue
import sys
import threading
import types
import unittest
from unittest.mock import Mock, call, mock_open, patch

import pixel_draw


class _SinglePixelGrid:
    shape = (1, 1)

    def __eq__(self, color_index):
        return color_index == 0


class _ColorMask:
    def __init__(self, color_index):
        self.color_index = color_index


class _TwoColorGrid:
    shape = (1, 2)

    def __eq__(self, color_index):
        return _ColorMask(color_index)


class _ArrayOps:
    @staticmethod
    def any(mask):
        return True

    @staticmethod
    def where(mask):
        if isinstance(mask, _ColorMask):
            return ([0], [mask.color_index])
        return [0], [0]

    @staticmethod
    def count_nonzero(mask):
        return 1


class _Screenshot:
    width = 1200
    height = 900

    def __init__(self, color):
        self.color = color
        self.sampled_at = None

    def getpixel(self, point):
        self.sampled_at = point
        return self.color


class PixelPaintingTests(unittest.TestCase):
    def test_legacy_calibration_filename_is_still_loaded(self):
        calibration = {"palette_rgb": [[0, 0, 0]]}
        mocked_open = mock_open(read_data='{"palette_rgb": [[0, 0, 0]]}')

        with (
            patch.object(pixel_draw.os.path, "exists", return_value=False),
            patch("builtins.open", mocked_open),
        ):
            loaded = pixel_draw._load_config()

        self.assertEqual(loaded, calibration)
        mocked_open.assert_called_once_with(
            pixel_draw.LEGACY_CONFIG_FILE, encoding="utf-8")

    def test_f9_toggles_pause_once_per_press_and_f11_is_ignored(self):
        class Listener:
            def __init__(self, on_press, on_release):
                self.on_press = on_press
                self.on_release = on_release

            def start(self):
                return self

        keyboard = types.SimpleNamespace(
            Key=types.SimpleNamespace(f9="f9", f10="f10", f11="f11", f12="f12"),
            Listener=Listener)
        pynput = types.ModuleType("pynput")
        pynput.keyboard = keyboard
        pause_toggle = Mock()

        with (
            patch.dict(sys.modules, {"pynput": pynput}),
            patch.object(pixel_draw, "log_event"),
        ):
            listener = pixel_draw._start_emergency_listener(
                on_pause_toggle=pause_toggle)
            listener.on_press("f9")
            listener.on_press("f9")
            listener.on_press("f11")
            listener.on_release("f9")
            listener.on_press("f9")

        self.assertEqual(pause_toggle.call_count, 2)

    def test_auto_remaining_checkbox_requires_manual_mode_and_captured_palette(self):
        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app.config = {
            "palette_rgb": [(0, 0, 0), (255, 255, 255)],
            "palette_pts": [(100, 100), (200, 200)],
        }
        app.manual = Mock()
        app.auto_select_remaining_check = Mock()
        app.auto_select_remaining_enabled = Mock()

        app.manual.get.return_value = False
        app._update_manual_options()
        app.auto_select_remaining_check.configure.assert_called_with(
            state="disabled")
        app.auto_select_remaining_enabled.set.assert_called_with(False)

        app.manual.get.return_value = True
        app._update_manual_options()
        app.auto_select_remaining_check.configure.assert_called_with(
            state="normal")

        app.config["palette_pts"] = None
        app._update_manual_options()
        app.auto_select_remaining_check.configure.assert_called_with(
            state="disabled")
        app.auto_select_remaining_enabled.set.assert_called_with(False)

    def test_f10_confirmation_is_queued_for_gui_thread(self):
        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app.events = queue.Queue()
        app.manual_color_event = threading.Event()

        with patch.object(pixel_draw, "log_event"):
            app.request_manual_confirm()

        self.assertFalse(app.manual_color_event.is_set())
        self.assertEqual(app.events.get_nowait(), ("manual_confirm", None))

    def test_confirming_first_manual_color_activates_auto_remaining_mode(self):
        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app.manual_color_event = threading.Event()
        app.auto_select_remaining_enabled = Mock()
        app.auto_select_remaining_enabled.get.return_value = True
        app.manual_selected_button = Mock()
        app._set_status = Mock()

        with patch.object(pixel_draw, "log_event"):
            app._confirm_manual_color()

        self.assertTrue(app.auto_select_remaining)
        self.assertTrue(app.manual_color_event.is_set())
        app.manual_selected_button.config.assert_called_once_with(
            state="disabled")
        self.assertIn("automatically", app._set_status.call_args.args[0])

    def test_manual_mode_can_auto_select_all_remaining_palette_colors(self):
        confirm_calls = []
        with (
            patch.object(pixel_draw, "_require_runtime_deps"),
            patch.object(pixel_draw, "np", _ArrayOps),
            patch.object(pixel_draw, "_click", return_value=True) as click,
            patch.object(pixel_draw, "log_event"),
        ):
            pixel_draw.STOP_EVENT.clear()
            pixel_draw.draw(
                _TwoColorGrid(), (10, 20, 30, 40),
                [(100, 100), (200, 200)], set(), 0.02, 2,
                manual=True, click_hold=0.05, automatic=True,
                on_manual_color=lambda color: (
                    confirm_calls.append(color) or "auto_remaining"))

        self.assertEqual(confirm_calls, [0])
        self.assertEqual(
            [call_args.args[:2] for call_args in click.call_args_list],
            [(15, 30), (200, 200), (25, 30)])

    def test_skip_color_parser_accepts_multiple_numbers_and_whitespace(self):
        self.assertEqual(pixel_draw._parse_skip_colors(" 1, 3 ", 4),
                         {0, 2})

    def test_skip_color_parser_accepts_blank_response(self):
        self.assertEqual(pixel_draw._parse_skip_colors("  ", 4), set())

    def test_skip_color_parser_rejects_invalid_or_out_of_range_numbers(self):
        for response in ("abc", "1,,2", "0", "5", "-1"):
            with self.subTest(response=response):
                with self.assertRaisesRegex(ValueError, "from 1 to 4"):
                    pixel_draw._parse_skip_colors(response, 4)

    def test_overlay_points_scale_to_automation_coordinates(self):
        self.assertEqual(pixel_draw._scale_point(400, 300, 2, 1.5),
                         (800, 450))

    def test_palette_capture_samples_rgb_and_saves_automation_position(self):
        screenshot = _Screenshot((12, 34, 56))
        point, rgb = pixel_draw._capture_palette_sample(
            400, 300, screenshot, 2, 2, 1.5, 1.25)

        self.assertEqual(screenshot.sampled_at, (800, 600))
        self.assertEqual(rgb, (12, 34, 56))
        self.assertEqual(point, (600, 375))

    def test_draw_clicks_captured_palette_position_before_pixel(self):
        captured_palette_position = (1332, 473)
        with (
            patch.object(pixel_draw, "_require_runtime_deps"),
            patch.object(pixel_draw, "np", _ArrayOps),
            patch.object(pixel_draw, "_click", return_value=True) as click,
            patch.object(pixel_draw, "log_event"),
        ):
            pixel_draw.STOP_EVENT.clear()
            pixel_draw.draw(
                _SinglePixelGrid(), (10, 20, 30, 40),
                [captured_palette_position], set(), 0.02, 1,
                click_hold=0.05, automatic=True)

        self.assertEqual(
            click.call_args_list,
            [call(1332, 473, 0.05, 0.02, None),
             call(20, 30, 0.05, 0.02, None, unittest.mock.ANY)])

    def test_default_timing_values_are_valid(self):
        self.assertEqual(pixel_draw.DEFAULT_DELAY, 0.02)
        self.assertEqual(pixel_draw.DEFAULT_CLICK_HOLD, 0.05)
        pixel_draw._validate_timing(
            pixel_draw.DEFAULT_DELAY, pixel_draw.DEFAULT_CLICK_HOLD)

    def test_timing_validation_rejects_invalid_values(self):
        for delay in (-0.01, float("nan"), float("inf")):
            with self.subTest(delay=delay):
                with self.assertRaisesRegex(ValueError, "Delay"):
                    pixel_draw._validate_timing(delay, 0.05)

        for click_hold in (0, -0.01, float("nan"), float("inf")):
            with self.subTest(click_hold=click_hold):
                with self.assertRaisesRegex(ValueError, "Click hold"):
                    pixel_draw._validate_timing(0.02, click_hold)


if __name__ == "__main__":
    unittest.main()
