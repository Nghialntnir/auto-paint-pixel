import unittest
from unittest.mock import call, patch

import bangbang_draw


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
    def test_manual_mode_can_auto_select_all_remaining_palette_colors(self):
        confirm_calls = []
        with (
            patch.object(bangbang_draw, "_require_runtime_deps"),
            patch.object(bangbang_draw, "np", _ArrayOps),
            patch.object(bangbang_draw, "_click", return_value=True) as click,
            patch.object(bangbang_draw, "log_event"),
        ):
            bangbang_draw.STOP_EVENT.clear()
            bangbang_draw.draw(
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
        self.assertEqual(bangbang_draw._parse_skip_colors(" 1, 3 ", 4),
                         {0, 2})

    def test_skip_color_parser_accepts_blank_response(self):
        self.assertEqual(bangbang_draw._parse_skip_colors("  ", 4), set())

    def test_skip_color_parser_rejects_invalid_or_out_of_range_numbers(self):
        for response in ("abc", "1,,2", "0", "5", "-1"):
            with self.subTest(response=response):
                with self.assertRaisesRegex(ValueError, "from 1 to 4"):
                    bangbang_draw._parse_skip_colors(response, 4)

    def test_overlay_points_scale_to_automation_coordinates(self):
        self.assertEqual(bangbang_draw._scale_point(400, 300, 2, 1.5),
                         (800, 450))

    def test_palette_capture_samples_rgb_and_saves_automation_position(self):
        screenshot = _Screenshot((12, 34, 56))
        point, rgb = bangbang_draw._capture_palette_sample(
            400, 300, screenshot, 2, 2, 1.5, 1.25)

        self.assertEqual(screenshot.sampled_at, (800, 600))
        self.assertEqual(rgb, (12, 34, 56))
        self.assertEqual(point, (600, 375))

    def test_draw_clicks_captured_palette_position_before_pixel(self):
        captured_palette_position = (1332, 473)
        with (
            patch.object(bangbang_draw, "_require_runtime_deps"),
            patch.object(bangbang_draw, "np", _ArrayOps),
            patch.object(bangbang_draw, "_click", return_value=True) as click,
            patch.object(bangbang_draw, "log_event"),
        ):
            bangbang_draw.STOP_EVENT.clear()
            bangbang_draw.draw(
                _SinglePixelGrid(), (10, 20, 30, 40),
                [captured_palette_position], set(), 0.02, 1,
                click_hold=0.05, automatic=True)

        self.assertEqual(
            click.call_args_list,
            [call(1332, 473, 0.05, 0.02, None),
             call(20, 30, 0.05, 0.02, None, unittest.mock.ANY)])

    def test_default_timing_values_are_valid(self):
        self.assertEqual(bangbang_draw.DEFAULT_DELAY, 0.02)
        self.assertEqual(bangbang_draw.DEFAULT_CLICK_HOLD, 0.05)
        bangbang_draw._validate_timing(
            bangbang_draw.DEFAULT_DELAY, bangbang_draw.DEFAULT_CLICK_HOLD)

    def test_timing_validation_rejects_invalid_values(self):
        for delay in (-0.01, float("nan"), float("inf")):
            with self.subTest(delay=delay):
                with self.assertRaisesRegex(ValueError, "Delay"):
                    bangbang_draw._validate_timing(delay, 0.05)

        for click_hold in (0, -0.01, float("nan"), float("inf")):
            with self.subTest(click_hold=click_hold):
                with self.assertRaisesRegex(ValueError, "Click hold"):
                    bangbang_draw._validate_timing(0.02, click_hold)


if __name__ == "__main__":
    unittest.main()
