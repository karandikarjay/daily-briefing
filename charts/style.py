"""Transparent charts with outlines that stay legible on light and dark email UI."""

import matplotlib.patheffects as effects
import numpy as np
from PIL import Image, ImageFilter

from config import CHART_DPI, GRID_COLOR


def finish_chart(ax, filename):
    """Keep titles in HTML; protect raster lines and labels with a thin light halo."""
    ax.figure.patch.set_alpha(0)
    ax.patch.set_alpha(0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(True, linestyle='--', linewidth=0.6, alpha=0.3, color=GRID_COLOR)
    ax.tick_params(colors='#46565c', labelsize=12, length=0)
    for line in ax.lines:
        line.set_path_effects([effects.Stroke(linewidth=3.2, foreground='#f5f5f5'), effects.Normal()])
    for label in [*ax.get_xticklabels(), *ax.get_yticklabels(), *ax.texts,
                  ax.xaxis.get_offset_text(), ax.yaxis.get_offset_text()]:
        label.set_color('#46565c')
        label.set_path_effects([effects.Stroke(linewidth=1.6, foreground='#f5f5f5'), effects.Normal()])
    ax.figure.tight_layout()
    ax.figure.savefig(filename, dpi=CHART_DPI, bbox_inches='tight', transparent=True)


def transparent_screenshot(source, destination):
    """Remove a white screenshot matte, preserving color and antialiased edges.

    Recover alpha from the darkest channel, then undo compositing against white.
    A one-pixel halo protects dark labels and the filled bond series. Pale grid
    pixels do not seed the halo, keeping the surrounding canvas transparent.
    """
    with Image.open(source) as image:
        rgb = np.asarray(image.convert('RGB'), dtype=float)
    alpha = 255 - rgb.min(axis=2)
    foreground = np.zeros_like(rgb)
    np.divide((rgb - 255 + alpha[..., None]) * 255, alpha[..., None],
              out=foreground, where=alpha[..., None] != 0)
    rgba = np.dstack((np.clip(foreground, 0, 255), alpha)).astype('uint8')
    ink = Image.fromarray(np.where(alpha > 100, 255, 0).astype('uint8'))
    halo = Image.new('RGBA', ink.size, '#f5f5f5')
    halo.putalpha(ink.filter(ImageFilter.MaxFilter(3)))
    Image.alpha_composite(halo, Image.fromarray(rgba)).save(destination)
