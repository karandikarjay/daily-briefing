"""Check transparency without losing screenshot evidence or raster labels."""
import tempfile
import unittest
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image

from charts.style import finish_chart, transparent_screenshot


class ChartStyleTests(unittest.TestCase):
    def test_plot_exports_transparent_canvas_and_outlined_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chart.png'
            fig, ax = plt.subplots()
            ax.plot([1, 2, 3], [4, 2, 5])
            ax.annotate('5.00', (3, 5))
            finish_chart(ax, path)
            with Image.open(path) as image:
                self.assertEqual(image.getchannel('A').getextrema(), (0, 255))
                self.assertEqual(image.getpixel((0, 0))[3], 0)
            self.assertTrue(ax.texts[0].get_path_effects())
            self.assertTrue(ax.get_xticklabels()[0].get_path_effects())
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
