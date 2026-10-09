import unittest
from unittest.mock import call, patch

import bangbang_draw


class _SinglePixelGrid:
    shape = (1, 1)

    def __eq__(self, color_index):
        return color_index == 0


class _ArrayOps:
    @staticmethod
    def any(mask):
        return mask

    @staticmethod
    def where(mask):
        return [0], [0]

    @staticmethod
    def count_nonzero(mask):
        return int(mask)


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
