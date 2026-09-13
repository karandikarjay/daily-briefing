"""Check transparency without losing screenshot evidence or raster labels."""
import tempfile
import unittest
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw
from datetime import datetime

from charts.style import finish_chart, transparent_screenshot, LABEL_COLOR
from config import CHART_COLOR


class ChartStyleTests(unittest.TestCase):
    def test_plot_exports_transparent_canvas_and_unboxed_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chart.png'
            fig, ax = plt.subplots()
            ax.plot([datetime(2025, 9, 1), datetime(2026, 3, 1), datetime(2026, 9, 1)], [4, 2, 5])
            ax.annotate('5.00', (datetime(2026, 9, 1), 5))
            finish_chart(ax, path)
            with Image.open(path) as image:
                self.assertEqual(image.getchannel('A').getextrema(), (0, 255))
                self.assertEqual(image.getpixel((0, 0))[3], 0)
            for label in (ax.texts[0], ax.get_xticklabels()[0]):
                self.assertFalse(label.get_path_effects())
                self.assertIsNone(label.get_bbox_patch())
                self.assertEqual(label.get_color(), LABEL_COLOR)
                self.assertGreaterEqual(label.get_fontsize(), 16)
            self.assertLessEqual(len(ax.get_xticks()), 4)
            self.assertFalse(any(line.get_visible() for line in ax.get_xgridlines()))
            self.assertFalse(ax.lines[0].get_path_effects())
            plt.close(fig)

    def test_screenshot_removes_matte_and_maps_series_palette(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.png'
            target = Path(directory) / 'target.png'
            original = Image.new('RGB', (20, 20), 'white')
            original.putpixel((10, 10), (0, 80, 150))
            original.putpixel((5, 5), (220, 220, 220))
            original.save(source)
            transparent_screenshot(source, target)
            with Image.open(target) as image:
                self.assertEqual(image.getpixel((0, 0))[3], 0)
                self.assertEqual(image.getpixel((10, 10)), tuple(int(CHART_COLOR[i:i+2], 16) for i in (1, 3, 5)) + (255,))
                self.assertEqual(image.getpixel((9, 10))[3], 0)
                self.assertLess(image.getpixel((5, 5))[3], 100)

    def test_screenshot_labels_have_no_backing_or_halo(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.png'
            target = Path(directory) / 'target.png'
            original = Image.new('RGB', (200, 100), 'white')
            # White space inside a glyph stays transparent.
            ImageDraw.Draw(original).rectangle((30, 30, 38, 38), outline='#333333')
            original.save(source)
            transparent_screenshot(source, target)
            with Image.open(target) as image:
                self.assertEqual(image.getpixel((34, 34))[3], 0)
                self.assertEqual(image.getpixel((30, 30)), (137, 137, 137, 255))
                self.assertEqual(image.getpixel((0, 0))[3], 0)
