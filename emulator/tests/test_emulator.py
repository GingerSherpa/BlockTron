from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from emulator.server import (
    CODE_PATH,
    ConfigError,
    build_display_config,
    dim_color,
    extract_source_config,
    parse_bdf,
    source_revision,
)


class SourceConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = CODE_PATH.read_text(encoding="utf-8")

    def test_extracts_matrix_and_btc_mode_layers(self) -> None:
        _, width, height, layers = extract_source_config(self.source)
        by_role = {layer["role"]: layer for layer in layers}

        self.assertEqual((width, height), (64, 32))
        self.assertEqual(
            set(by_role),
            {
                "price",
                "blockheight",
                "moscow",
                "status_pixel",
                "ticker",
                "time",
            },
        )
        self.assertEqual(by_role["price"]["position"], [2, -6])
        self.assertEqual(by_role["price"]["font"], "/fonts/Arial-Bold-12.bdf")
        self.assertEqual(by_role["price"]["color"], 0xFF4500)
        self.assertEqual(by_role["status_pixel"]["position"], [60, -2])
        self.assertEqual(by_role["status_pixel"]["font"], "/fonts/4x6-lean.bdf")
        self.assertEqual(by_role["ticker"]["position"], [0, 18])
        self.assertTrue(by_role["ticker"]["scrolling"])

    def test_reads_matrix_dimensions_from_constructor(self) -> None:
        changed = self.source.replace("width=64,", "width=80,", 1)

        _, width, height, _ = extract_source_config(changed)

        self.assertEqual((width, height), (80, 32))

    def test_reports_syntax_errors_without_importing_firmware(self) -> None:
        with self.assertRaisesRegex(ConfigError, "Source/code.py:1"):
            extract_source_config("this is not valid Python:")

    def test_dim_color_matches_firmware_integer_scaling(self) -> None:
        self.assertEqual(dim_color(0xFF4500, 10), 0xFF4500)
        self.assertEqual(dim_color(0xFF4500, 5), 0x7F2200)
        self.assertEqual(dim_color(0x000001, 1), 0x000001)


class FontTests(unittest.TestCase):
    def test_parses_ascii_glyph_metrics_and_pixels(self) -> None:
        font = parse_bdf(CODE_PATH.parent / "fonts" / "Arial-Bold-12.bdf")
        glyph = font["glyphs"][str(ord("C"))]

        self.assertEqual(font["ascent"], 15)
        self.assertEqual(glyph["width"], 10)
        self.assertEqual(glyph["height"], 12)
        self.assertEqual(glyph["shiftX"], 12)
        self.assertEqual(glyph["rows"][0], "0001111100")


class DisplayConfigTests(unittest.TestCase):
    def test_builds_browser_config_without_secrets(self) -> None:
        config = build_display_config()
        serialized = json.dumps(config).lower()

        self.assertEqual(config["display"], {"width": 64, "height": 32})
        self.assertEqual(config["source"]["mode"], "btc")
        self.assertEqual(len(config["btc"]["layers"]), 6)
        self.assertEqual(len(config["fonts"]), 3)
        self.assertNotIn("password", serialized)
        self.assertNotIn("wifi_ssid", serialized)
        self.assertNotIn("proxy_base", serialized)
        self.assertNotIn("device_keys", serialized)

    def test_revision_tracks_source_and_fonts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            source_root = project_root / "Source"
            fonts_root = source_root / "fonts"
            fonts_root.mkdir(parents=True)
            code_path = source_root / "code.py"
            font_path = fonts_root / "display.bdf"
            code_path.write_text("VALUE = 1\n", encoding="utf-8")
            font_path.write_text("FONT A\n", encoding="utf-8")
            initial = source_revision(project_root)

            code_path.write_text("VALUE = 2\n", encoding="utf-8")
            code_change = source_revision(project_root)
            code_path.write_text("VALUE = 1\n", encoding="utf-8")
            font_path.write_text("FONT B\n", encoding="utf-8")
            font_change = source_revision(project_root)

        self.assertNotEqual(initial, code_change)
        self.assertNotEqual(initial, font_change)


if __name__ == "__main__":
    unittest.main()
