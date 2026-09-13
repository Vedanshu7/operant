"""
Pixel edits on saved screenshots.

Import as:

import operant.helpers.images as images
"""

from __future__ import annotations

import collections.abc
import pathlib

import PIL.Image
import PIL.ImageDraw

import operant.domain.models.digest as digest

# Pixels added on each side, so a field's border and focus ring are
# covered too.
_PAD_PX = 3


def black_out(
    path: pathlib.Path, boxes: collections.abc.Sequence[digest.Box]
) -> None:
    """
    Paint each window-normalised box black in the PNG at ``path``.

    :param path: A screenshot of the window the boxes are relative to;
        rewritten in place.
    :param boxes: Rectangles as fractions of the window, 0..1.
    """
    with PIL.Image.open(path) as image:
        canvas = image.convert("RGB")
    width, height = canvas.size
    draw = PIL.ImageDraw.Draw(canvas)
    for box in boxes:
        draw.rectangle(
            (
                max(0, int(box.x * width) - _PAD_PX),
                max(0, int(box.y * height) - _PAD_PX),
                min(width - 1, int((box.x + box.w) * width) + _PAD_PX),
                min(height - 1, int((box.y + box.h) * height) + _PAD_PX),
            ),
            fill=(0, 0, 0),
        )
    canvas.save(path, format="PNG")
