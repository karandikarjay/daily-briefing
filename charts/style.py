"""Transparent charts with a restrained palette shared by light and dark email."""

import matplotlib.dates as dates
from matplotlib.ticker import FixedLocator, MaxNLocator
import numpy as np
from PIL import Image

from config import CHART_COLOR, CHART_DPI, GRID_COLOR

LABEL_COLOR = '#898989'


def finish_chart(ax, filename):
    """Use large solid labels, sparse horizontal guides, and unoutlined lines."""
    ax.figure.patch.set_alpha(0)
    ax.patch.set_alpha(0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(False, which='both', axis='both')
    ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax.grid(True, axis='y', linestyle='-', linewidth=0.6, alpha=0.22, color=GRID_COLOR)
    # Both native chart collectors plot datetime data. Leave numeric axes alone.
    if isinstance(ax.xaxis.get_major_locator(), dates.DateLocator):
        start, end = ax.dataLim.intervalx
        ax.xaxis.set_major_locator(FixedLocator(np.linspace(start, end, 4)))
        ax.xaxis.set_major_formatter(dates.DateFormatter("%b ’%y"))
    ax.tick_params(colors=LABEL_COLOR, labelsize=16, length=0, pad=10)
    for line in ax.lines:
        line.set_color(CHART_COLOR)
        line.set_linewidth(2.4)
        line.set_path_effects([])
    for label in [*ax.get_xticklabels(), *ax.get_yticklabels(), *ax.texts,
                  ax.xaxis.get_offset_text(), ax.yaxis.get_offset_text()]:
        label.set_color(LABEL_COLOR)
        label.set_fontsize(16)
        label.set_fontweight('medium')
        label.set_path_effects([])
        label.set_bbox(None)
    ax.figure.tight_layout()
    ax.figure.savefig(filename, dpi=CHART_DPI, bbox_inches='tight', transparent=True)


def transparent_screenshot(source, destination):
    """Restyle the publisher's bond screenshot without moving its data or labels.

    Remove its white matte and map neutral ink to gray and blue ink to teal.
    Dark label cores are opaque, while pale grid pixels stay faint. Preserve
    other colored annotations (such as the publisher's red percentage badge).
    Screenshot dates and tick positions remain those supplied by the publisher.
    """
    with Image.open(source) as image:
        rgb = np.asarray(image.convert('RGB'), dtype=float)
    alpha = 255 - rgb.min(axis=2)
    foreground = np.zeros_like(rgb)
    np.divide((rgb - 255 + alpha[..., None]) * 255, alpha[..., None],
              out=foreground, where=alpha[..., None] != 0)
    neutral = rgb.max(axis=2) - rgb.min(axis=2) < 12
    blue = (~neutral) & (rgb[..., 2] > rgb[..., 0])
    foreground[neutral] = [137, 137, 137]
    foreground[blue] = [int(CHART_COLOR[i:i + 2], 16) for i in (1, 3, 5)]
    # Solid glyph interiors, with coverage retained at antialiased edges.
    alpha[neutral] = np.minimum(255, alpha[neutral] * 255 / 160)
    rgba = np.dstack((np.clip(foreground, 0, 255), alpha)).astype('uint8')
    Image.fromarray(rgba).save(destination)
