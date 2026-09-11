"""Check transparency without losing screenshot evidence or raster labels."""
import tempfile
import unittest
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw

from charts.style import finish_chart, transparent_screenshot


class ChartStyleTests(unittest.TestCase):
    def test_plot_exports_transparent_canvas_and_solid_backed_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chart.png'
            fig, ax = plt.subplots()
            ax.plot([1, 2, 3], [4, 2, 5])
            ax.annotate('5.00', (3, 5))
            finish_chart(ax, path)
            with Image.open(path) as image:
                self.assertEqual(image.getchannel('A').getextrema(), (0, 255))
                self.assertEqual(image.getpixel((0, 0))[3], 0)
            for label in (ax.texts[0], ax.get_xticklabels()[0]):
                self.assertFalse(label.get_path_effects())
                self.assertEqual(label.get_bbox_patch().get_facecolor()[3], 1)
                self.assertGreaterEqual(label.get_fontsize(), 14)
            plt.close(fig)

    def test_screenshot_removes_matte_and_preserves_series_color(self):
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
                self.assertEqual(image.getpixel((10, 10)), (0, 80, 150, 255))
                self.assertGreater(image.getpixel((9, 10))[3], 0)
                restored = Image.alpha_composite(Image.new('RGBA', image.size, 'white'), image)
                self.assertEqual(restored.getpixel((5, 5))[:3], (220, 220, 220))

    def test_screenshot_label_counters_have_opaque_backing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.png'
            target = Path(directory) / 'target.png'
            original = Image.new('RGB', (200, 100), 'white')
            # A hollow glyph must get a solid backing, not just an outline.
            ImageDraw.Draw(original).rectangle((30, 30, 38, 38), outline='#333333')
            original.save(source)
            transparent_screenshot(source, target)
            with Image.open(target) as image:
                self.assertEqual(image.getpixel((34, 34)), (245, 245, 245, 255))
                self.assertEqual(image.getpixel((0, 0))[3], 0)
