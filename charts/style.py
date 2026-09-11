"""Transparent plots with solid, backed labels for light and dark email UI."""

import matplotlib.patheffects as effects
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from config import CHART_DPI, GRID_COLOR


def finish_chart(ax, filename):
    """Keep titles in HTML and give solid labels their own high-contrast surface."""
    ax.figure.patch.set_alpha(0)
    ax.patch.set_alpha(0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(True, linestyle='--', linewidth=0.6, alpha=0.3, color=GRID_COLOR)
    ax.tick_params(colors='#263238', labelsize=14, length=0, pad=8)
    for line in ax.lines:
        line.set_path_effects([effects.Stroke(linewidth=3.2, foreground='#f5f5f5'), effects.Normal()])
    for label in [*ax.get_xticklabels(), *ax.get_yticklabels(), *ax.texts,
                  ax.xaxis.get_offset_text(), ax.yaxis.get_offset_text()]:
        label.set_color('#263238')
        label.set_fontsize(14)
        label.set_fontweight('medium')
        label.set_path_effects([])
        label.set_bbox(dict(facecolor='#f5f5f5', edgecolor='none',
                            boxstyle='round,pad=0.18', alpha=1))
    ax.figure.tight_layout()
    ax.figure.savefig(filename, dpi=CHART_DPI, bbox_inches='tight', transparent=True)


def transparent_screenshot(source, destination):
    """Remove a white screenshot matte, preserving color and antialiased edges.

    Recover alpha from the darkest channel, then undo compositing against white.
    Keep the series halo, but place neutral screenshot labels on small opaque
    rectangles so their original solid glyphs remain readable in either theme.
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
    # Group nearby neutral glyphs into label-sized patches. Long axes and
    # grid lines are excluded so the plot itself remains transparent.
    neutral = (rgb.max(axis=2) - rgb.min(axis=2) < 12) & (alpha > 100)
    neutral[:, neutral.sum(axis=0) > rgb.shape[0] * 0.4] = False
    neutral[neutral.sum(axis=1) > rgb.shape[1] * 0.4, :] = False
    grouped = np.array(Image.fromarray((neutral * 255).astype('uint8'))
                       .filter(ImageFilter.MaxFilter(9))) > 0
    seen = np.zeros(grouped.shape, dtype=bool)
    height, width = grouped.shape
    draw = ImageDraw.Draw(halo)
    for y, x in zip(*np.nonzero(grouped)):
        if seen[y, x]:
            continue
        stack = [(y, x)]
        seen[y, x] = True
        left = right = x
        top = bottom = y
        while stack:
            cy, cx = stack.pop()
            left, right = min(left, cx), max(right, cx)
            top, bottom = min(top, cy), max(bottom, cy)
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < height and 0 <= nx < width and grouped[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if bottom - top < height * 0.2 and right - left < width * 0.3:
            draw.rounded_rectangle((left, top, right, bottom), radius=2, fill='#f5f5f5')
    Image.alpha_composite(halo, Image.fromarray(rgba)).save(destination)
