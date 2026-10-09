import queue
import sys
import tempfile
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
    def test_grid_for_box_preserves_landscape_and_portrait_proportions(self):
        self.assertEqual(pixel_draw.grid_for_box((0, 0, 101, 51), 10),
                         (10, 5))
        self.assertEqual(pixel_draw.grid_for_box((0, 0, 40, 100), 10),
                         (4, 10))

    def test_grid_for_box_handles_narrow_area_and_rejects_invalid_input(self):
        self.assertEqual(pixel_draw.grid_for_box((4, 8, 5, 1008), 60),
                         (1, 60))
        for box, max_cells in (
                ((0, 0, 0, 10), 10),
                ((0, 0, 10, 10), 0),
                ((0, 0, 10, 10), -1),
                ((0, 0, 10, 10), 1.5),
                ((0, 0, 10, 10), True)):
            with self.subTest(box=box, max_cells=max_cells):
                with self.assertRaises(ValueError):
                    pixel_draw.grid_for_box(box, max_cells)

    def test_grid_for_box_handles_extreme_aspect_ratios_and_small_canvas(self):
        cases = (
            ((0, 0, 10000, 4), 60, (60, 1)),
            ((0, 0, 4, 10000), 60, (1, 60)),
            ((0, 0, 3, 2), 1, (1, 1)),
            ((0, 0, 100, 1), 260, (100, 1)),
        )
        for box, max_cells, expected in cases:
            with self.subTest(box=box, max_cells=max_cells):
                self.assertEqual(
                    pixel_draw.grid_for_box(box, max_cells), expected)

    def test_grid_for_box_caps_oversized_resolution_to_screen_coordinates(self):
        self.assertEqual(
            pixel_draw.grid_for_box((20, 30, 120, 80), 1000), (100, 50))

    def test_cell_center_maps_first_middle_and_last_in_non_divisible_box(self):
        box = (10, 20, 21, 29)
        self.assertEqual(pixel_draw.cell_center(box, 4, 3, 0, 0), (11, 21))
        self.assertEqual(pixel_draw.cell_center(box, 4, 3, 2, 1), (16, 24))
        self.assertEqual(pixel_draw.cell_center(box, 4, 3, 3, 2), (19, 27))

    def test_cell_center_stays_inside_small_landscape_and_portrait_boxes(self):
        for box, grid_w, grid_h in (
                ((-2, 4, -1, 5), 4, 3),
                ((4, -2, 5, -1), 3, 4),
                ((8, 9, 9, 10), 1, 1)):
            x1, y1, x2, y2 = box
            for row in range(grid_h):
                for col in range(grid_w):
                    with self.subTest(box=box, col=col, row=row):
                        x, y = pixel_draw.cell_center(
                            box, grid_w, grid_h, col, row)
                        self.assertTrue(x1 <= x < x2)
                        self.assertTrue(y1 <= y < y2)

    def test_cell_center_rejects_cells_outside_grid(self):
        with self.assertRaisesRegex(ValueError, "inside the drawing grid"):
            pixel_draw.cell_center((0, 0, 5, 5), 2, 2, 2, 0)

    def test_grid_exceeding_screen_area_is_reported_without_changing_grid(self):
        box = (0, 0, 100, 50)
        self.assertFalse(pixel_draw.grid_exceeds_screen_area(box, (100, 50)))
        self.assertTrue(pixel_draw.grid_exceeds_screen_area(box, (101, 50)))
        self.assertTrue(pixel_draw.grid_exceeds_screen_area(box, (100, 51)))
        mapped_x = {
            pixel_draw.cell_center(box, 101, 50, col, 0)[0]
            for col in range(101)
        }
        self.assertLess(len(mapped_x), 101)
        with self.assertRaises(ValueError):
            pixel_draw.grid_exceeds_screen_area(box, (0, 10))

    def test_prepare_image_uses_shared_grid_and_box(self):
        expected_indices = object()
        with patch.object(
                pixel_draw, "quantize", return_value=expected_indices) as quant:
            idx, grid_size, box, palette = pixel_draw.prepare_image(
                "image.png", [0, 0, 101, 51], 10, [[0, 0, 0]], False)

        self.assertIs(idx, expected_indices)
        self.assertEqual(grid_size, (10, 5))
        self.assertEqual(box, (0, 0, 101, 51))
        self.assertEqual(palette, [(0, 0, 0)])
        quant.assert_called_once_with(
            "image.png", (10, 5), [(0, 0, 0)], False)

    def test_prepare_image_passes_proportional_grid_to_quantizer(self):
        cases = (
            ([0, 0, 10000, 4], 60, (60, 1)),
            ([0, 0, 4, 10000], 60, (1, 60)),
            ([0, 0, 3, 2], 1, (1, 1)),
        )
        for box, max_cells, expected_grid in cases:
            with self.subTest(box=box):
                with patch.object(pixel_draw, "quantize") as quantize:
                    pixel_draw.prepare_image(
                        "image.png", box, max_cells, [(0, 0, 0)], False)
                self.assertEqual(quantize.call_args.args[1], expected_grid)

    def test_quantize_returns_indices_with_grid_height_and_width(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = pixel_draw.os.path.join(temp_dir, "source.png")
            image = pixel_draw.Image.new("RGB", (4, 2))
            image.putpixel((0, 0), (0, 0, 0))
            image.putpixel((1, 0), (0, 0, 0))
            image.putpixel((2, 0), (255, 255, 255))
            image.putpixel((3, 0), (255, 255, 255))
            image.putpixel((0, 1), (0, 0, 0))
            image.putpixel((1, 1), (0, 0, 0))
            image.putpixel((2, 1), (255, 255, 255))
            image.putpixel((3, 1), (255, 255, 255))
            image.save(image_path)

            indices = pixel_draw.quantize(
                image_path, (2, 1), [(0, 0, 0), (255, 255, 255)], False)

        self.assertEqual(indices.shape, (1, 2))
        self.assertEqual(indices.tolist(), [[0, 1]])

    def test_saved_configuration_rejects_invalid_area_and_palette_positions(self):
        with self.assertRaisesRegex(ValueError, "positive width and height"):
            pixel_draw._validate_config({"box": [1, 2, 1, 4]})
        with self.assertRaisesRegex(ValueError, "one integer screen"):
            pixel_draw._validate_config({
                "palette_rgb": [[0, 0, 0]],
                "palette_pts": [[10, 20], [30, 40]],
            })

    def test_palette_resize_preserves_valid_skips_and_reports_removed_indices(self):
        config = {"skip_colors": [0, 2, 4]}

        removed = pixel_draw._preserve_skip_colors(config, 3)

        self.assertEqual(config["skip_colors"], [0, 2])
        self.assertEqual(removed, [4])

    def test_click_estimate_accounts_for_skipped_colors_and_duplicate_pass(self):
        class PixelCounts:
            def __eq__(self, color):
                return (2, 2, 2)[color]

        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app.config = {
            "palette_rgb": [(0, 0, 0), (1, 1, 1), (2, 2, 2)],
            "skip_colors": [1],
        }
        app._prepared_image = {"idx": PixelCounts()}
        app.duplicate_pass_enabled = Mock()
        app.duplicate_pass_enabled.get.return_value = True
        app.additional_passes = Mock()
        app.additional_passes.get.return_value = "2"
        app.click_estimate = Mock()

        with patch.object(
                pixel_draw, "np",
                types.SimpleNamespace(count_nonzero=lambda count: count)):
            app._update_click_estimate()

        app.click_estimate.set.assert_called_once_with(
            "Estimated pixel clicks: 12 (3 passes)")

    def test_gui_additional_redraws_default_to_one_and_control_estimate(self):
        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app.duplicate_pass_enabled = Mock()
        app.duplicate_pass_enabled.get.return_value = False
        app.additional_passes = Mock()
        app.additional_passes.get.return_value = "1"
        app.additional_passes_entry = Mock()
        app._update_click_estimate = Mock()

        app._update_duplicate_pass_controls()
        app.additional_passes_entry.configure.assert_called_once_with(
            state="disabled")
        app._update_click_estimate.assert_called_once_with()

        app.duplicate_pass_enabled.get.return_value = True
        app._update_duplicate_pass_controls()
        app.additional_passes_entry.configure.assert_called_with(
            state="normal")
        self.assertEqual(app._update_click_estimate.call_count, 2)

    def test_grid_enter_or_focus_refreshes_summary_and_preview(self):
        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app.grid_count = Mock()
        app.grid_count.get.return_value = "10"
        app.grid_summary = Mock()
        app.click_estimate = Mock()
        app.duplicate_pass_enabled = Mock()
        app.duplicate_pass_enabled.get.return_value = False
        app.config = {
            "box": (0, 0, 101, 51),
            "palette_rgb": [(0, 0, 0)],
            "skip_colors": [],
        }
        app._prepared_image = None
        app.image_path = Mock()
        app.image_path.get.return_value = "image.png"
        app._make_preview = Mock()
        app.status = Mock()

        result = app._refresh_grid_preview()

        self.assertEqual(result, "break")
        self.assertIn("10 \u00d7 5 cells", app.grid_summary.set.call_args.args[0])
        app._make_preview.assert_called_once_with()

    def test_grid_summary_warns_when_cells_exceed_screen_positions(self):
        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app.grid_count = Mock()
        app.grid_count.get.return_value = "101"
        app.grid_summary = Mock()
        app.click_estimate = Mock()
        app.duplicate_pass_enabled = Mock()
        app.duplicate_pass_enabled.get.return_value = False
        app.config = {"box": (0, 0, 100, 50), "palette_rgb": []}
        app._prepared_image = None

        app._update_grid_summary()

        self.assertIn("capped at 100", app.grid_summary.set.call_args.args[0])

    def test_additional_pass_count_validation(self):
        self.assertEqual(pixel_draw.validate_additional_passes(1), 1)
        self.assertEqual(
            pixel_draw.validate_additional_passes(
                pixel_draw.MAX_ADDITIONAL_PASSES),
            pixel_draw.MAX_ADDITIONAL_PASSES)
        for value in (0, -1, 1.5, True, 101):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Additional redraws"):
                    pixel_draw.validate_additional_passes(value)

    def test_palette_recapture_preserves_skips_and_reports_removed_choices(self):
        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app.color_count = Mock()
        app.color_count.get.return_value = "2"
        app.root = Mock()
        app.config = {
            "box": (0, 0, 100, 50),
            "palette_rgb": [(0, 0, 0), (255, 255, 255), (255, 0, 0)],
            "palette_pts": [(10, 10), (20, 20), (30, 30)],
            "skip_colors": [0, 2],
        }
        app.image_path = Mock()
        app.image_path.get.return_value = ""
        app._invalidate_preview = Mock()
        app._refresh_palette_list = Mock()
        app._save_config = Mock()
        app._set_status = Mock()

        with (
            patch.object(
                pixel_draw, "pick_palette",
                return_value=([(11, 11), (22, 22)],
                              [(1, 2, 3), (4, 5, 6)])),
            patch.object(pixel_draw, "log_event"),
        ):
            app._select_palette()

        self.assertEqual(app.config["skip_colors"], [0])
        app._refresh_palette_list.assert_called_once_with()
        self.assertIn(
            "Removed out-of-range skip choices (#3)",
            app._set_status.call_args.args[0])

    def test_legacy_calibration_filename_is_still_loaded(self):
        calibration = {"palette_rgb": [(0, 0, 0)], "palette_pts": None}
        mocked_open = mock_open(
            read_data='{"palette_rgb": [[0, 0, 0]], "palette_pts": null}')

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

    def test_duplicate_pass_redraws_color_before_selecting_the_next(self):
        progress = []

        def complete_click(_x, _y, _hold, _delay, _pause_event, callback=None):
            if callback is not None:
                callback()
            return True

        with (
            patch.object(pixel_draw, "_require_runtime_deps"),
            patch.object(pixel_draw, "np", _ArrayOps),
            patch.object(pixel_draw, "_click", side_effect=complete_click) as click,
            patch.object(pixel_draw, "log_event"),
        ):
            pixel_draw.STOP_EVENT.clear()
            pixel_draw.draw(
                _TwoColorGrid(), (10, 20, 30, 40),
                [(100, 100), (200, 200)], set(), 0.02, 2,
                click_hold=0.05, automatic=True,
                on_pixel=lambda *args: progress.append(args),
                duplicate_pass=True)

        self.assertEqual(
            [call_args.args[:2] for call_args in click.call_args_list],
            [(100, 100), (15, 30), (15, 30),
             (200, 200), (25, 30), (25, 30)])
        self.assertEqual(
            [(event[0], event[1], event[2]) for event in progress],
            [(0, 1, 2), (0, 2, 2), (1, 1, 2), (1, 2, 2)])

    def test_additional_passes_redraw_each_color_before_switching(self):
        def complete_click(_x, _y, _hold, _delay, _pause_event, callback=None):
            if callback is not None:
                callback()
            return True

        with (
            patch.object(pixel_draw, "_require_runtime_deps"),
            patch.object(pixel_draw, "np", _ArrayOps),
            patch.object(
                pixel_draw, "_click", side_effect=complete_click) as click,
            patch.object(pixel_draw, "log_event"),
        ):
            pixel_draw.STOP_EVENT.clear()
            completed = pixel_draw.draw(
                _TwoColorGrid(), (10, 20, 30, 40),
                [(100, 100), (200, 200)], set(), 0.02, 2,
                click_hold=0.05, automatic=True, duplicate_pass=True,
                additional_passes=3)

        self.assertTrue(completed)
        self.assertEqual(
            [call_args.args[:2] for call_args in click.call_args_list],
            [(100, 100), (15, 30), (15, 30), (15, 30), (15, 30),
             (200, 200), (25, 30), (25, 30), (25, 30), (25, 30)])

    def test_interrupted_duplicate_pass_logs_completed_and_planned_clicks(self):
        def click_then_interrupt(
                _x, _y, _hold, _delay, _pause_event, callback=None):
            if click.call_count == 2 and callback is not None:
                callback()
                return True
            return click.call_count < 3

        with (
            patch.object(pixel_draw, "_require_runtime_deps"),
            patch.object(pixel_draw, "np", _ArrayOps),
            patch.object(pixel_draw, "_click") as click,
            patch.object(pixel_draw, "log_event") as log,
        ):
            click.side_effect = click_then_interrupt
            pixel_draw.STOP_EVENT.clear()
            completed = pixel_draw.draw(
                _SinglePixelGrid(), (10, 20, 30, 40),
                [(100, 100)], set(), 0.02, 1,
                click_hold=0.05, automatic=True, duplicate_pass=True)

        self.assertFalse(completed)
        self.assertTrue(any(
            call_args.args[0] == "DRAW"
            and "completed 1/2 pixel clicks" in call_args.args[1]
            for call_args in log.call_args_list))

    def test_interactive_skip_reduces_final_click_plan(self):
        def complete_click(_x, _y, _hold, _delay, _pause_event, callback=None):
            if callback is not None:
                callback()
            return True

        with (
            patch.object(pixel_draw, "_require_runtime_deps"),
            patch.object(pixel_draw, "np", _ArrayOps),
            patch.object(pixel_draw, "_click", side_effect=complete_click),
            patch.object(pixel_draw, "ask_yes", side_effect=("s", "y")),
            patch.object(pixel_draw, "countdown", return_value=True),
            patch.object(pixel_draw, "log_event") as log,
        ):
            pixel_draw.STOP_EVENT.clear()
            completed = pixel_draw.draw(
                _TwoColorGrid(), (10, 20, 30, 40),
                [(100, 100), (200, 200)], set(), 0.02, 2,
                manual=True, click_hold=0.05, duplicate_pass=True)

        self.assertTrue(completed)
        self.assertTrue(any(
            call_args.args[0] == "DRAW"
            and "Completed 2/2 planned pixel clicks; 1 pixels skipped."
            in call_args.args[1]
            for call_args in log.call_args_list))

    def test_grid_change_invalidates_cached_preview_and_reports_valid_grid(self):
        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app._prepared_image = {"idx": object()}
        app._preview_signature = ("old",)
        app.preview_source = object()
        app.preview_image = object()
        app.preview_label = Mock()
        app.grid_summary = Mock()
        app.click_estimate = Mock()
        app.status = Mock()
        app.grid_count = Mock()
        app.grid_count.get.return_value = "10"
        app.duplicate_pass_enabled = Mock()
        app.duplicate_pass_enabled.get.return_value = False
        app.config = {"box": (0, 0, 101, 51), "palette_rgb": []}

        app._invalidate_preview()

        self.assertIsNone(app._prepared_image)
        self.assertIsNone(app._preview_signature)
        self.assertIsNone(app.preview_source)
        self.assertIsNone(app.preview_image)
        app.grid_summary.set.assert_called_with(
            "Grid resolution: 10 \u00d7 5 cells | Total: 50 cells")

    def test_image_data_cache_reuses_preview_quantization(self):
        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app.image_path = Mock()
        app.image_path.get.return_value = "image.png"
        app.color_count = Mock()
        app.color_count.get.return_value = "1"
        app.grid_count = Mock()
        app.grid_count.get.return_value = "10"
        app.use_dither = Mock()
        app.use_dither.get.return_value = False
        app.config = {
            "box": [0, 0, 101, 51],
            "palette_rgb": [[0, 0, 0]],
        }
        app._prepared_image = None
        first_indices = object()
        second_indices = object()
        prepared_values = [
            (first_indices, (10, 5), (0, 0, 101, 51), [(0, 0, 0)]),
            (second_indices, (8, 4), (0, 0, 101, 51), [(0, 0, 0)]),
        ]
        stat = types.SimpleNamespace(st_size=10, st_mtime_ns=20)

        with (
            patch.object(pixel_draw.os.path, "isfile", return_value=True),
            patch.object(pixel_draw.os, "stat", return_value=stat),
            patch.object(
                pixel_draw, "prepare_image",
                side_effect=prepared_values) as prepare,
        ):
            first = app._get_image_data()
            second = app._get_image_data()
            app.grid_count.get.return_value = "8"
            third = app._get_image_data()

        self.assertIs(first[0], first_indices)
        self.assertIs(second[0], first_indices)
        self.assertIs(third[0], second_indices)
        self.assertEqual(prepare.call_count, 2)
        self.assertEqual(prepare.call_args.args[2], 8)

    def test_palette_count_mismatch_blocks_preview_image_preparation(self):
        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app.image_path = Mock()
        app.image_path.get.return_value = "image.png"
        app.color_count = Mock()
        app.color_count.get.return_value = "2"
        app.grid_count = Mock()
        app.grid_count.get.return_value = "10"
        app.use_dither = Mock()
        app.use_dither.get.return_value = False
        app.config = {
            "box": (0, 0, 100, 50),
            "palette_rgb": [[0, 0, 0]],
            "palette_pts": [[10, 10]],
        }
        app._prepared_image = None

        with patch.object(pixel_draw.os.path, "isfile", return_value=True):
            with self.assertRaisesRegex(ValueError, "Capture the palette again"):
                app._get_image_data()

    def test_click_reports_a_released_press_even_when_stop_arrives_during_it(self):
        callback = Mock()
        stop = pixel_draw.STOP_EVENT
        stop.clear()
        automation = types.SimpleNamespace(
            moveTo=Mock(),
            mouseDown=Mock(side_effect=stop.set),
            mouseUp=Mock())

        try:
            with (
                patch.object(pixel_draw, "pyautogui", automation),
                patch.object(pixel_draw, "_wait_until_running", return_value=True),
            ):
                result = pixel_draw._click(
                    5, 7, 0.05, 0, on_click=callback)
        finally:
            stop.clear()

        self.assertFalse(result)
        callback.assert_called_once_with()

    def test_invalid_grid_input_does_not_refresh_or_use_stale_preview(self):
        app = pixel_draw.DrawingApp.__new__(pixel_draw.DrawingApp)
        app.grid_count = Mock()
        app.grid_count.get.return_value = ""
        app.grid_summary = Mock()
        app.click_estimate = Mock()
        app.duplicate_pass_enabled = Mock()
        app.duplicate_pass_enabled.get.return_value = False
        app.status = Mock()
        app.config = {"box": (0, 0, 100, 50)}
        app._prepared_image = {"idx": object()}
        app._preview_signature = ("stale",)
        app.preview_source = object()
        app.preview_image = object()
        app.preview_label = Mock()
        app._make_preview = Mock()

        result = app._refresh_grid_preview()

        self.assertEqual(result, "break")
        app._make_preview.assert_not_called()
        self.assertIsNone(app._prepared_image)
        self.assertIsNone(app._preview_signature)
        self.assertIsNone(app.preview_source)
        self.assertIsNone(app.preview_image)
        self.assertIn(
            "positive whole number",
            app.status.set.call_args.args[0])

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
