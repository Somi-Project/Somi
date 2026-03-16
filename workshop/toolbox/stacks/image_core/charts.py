from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import List, Optional

from config.settings import SESSION_MEDIA_DIR

_PLOT_IMPORT_ERROR = None

try:
    import matplotlib

    matplotlib.use("Agg")  # headless backend (no GUI required)
    import matplotlib.pyplot as plt
except Exception as e:  # defer runtime failure to chart-call sites
    matplotlib = None
    plt = None
    _PLOT_IMPORT_ERROR = e


@dataclass
class ImageAttachment:
    type: str  # "image"
    path: str
    mime: str = "image/png"
    title: Optional[str] = None


def _ensure_matplotlib_ready() -> None:
    if plt is None:
        detail = f": {_PLOT_IMPORT_ERROR}" if _PLOT_IMPORT_ERROR else ""
        raise RuntimeError(f"Matplotlib is unavailable{detail}")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _media_path(out_dir: str, prefix: str = "chart", ext: str = "png") -> str:
    ts = int(time.time() * 1000)
    return os.path.join(out_dir, f"{prefix}_{ts}.{ext}")


def bar_chart(
    title: str,
    labels: List[str],
    values: List[float],
    y_label: Optional[str] = None,
    out_dir: str = SESSION_MEDIA_DIR,
) -> ImageAttachment:
    if not labels or not values:
        raise ValueError("labels/values cannot be empty")
    if len(labels) != len(values):
        raise ValueError("labels and values must have same length")

    _ensure_matplotlib_ready()
    _ensure_dir(out_dir)
    out_path = _media_path(out_dir, prefix="bar")

    plt.figure()
    plt.bar(labels, values)
    plt.title(title or "Bar Chart")
    if y_label:
        plt.ylabel(y_label)
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    plt.close()

    return ImageAttachment(type="image", path=out_path, title=title or "Bar Chart")


def line_chart(
    title: str,
    x: List[float],
    y: List[float],
    x_label: Optional[str] = None,
    y_label: Optional[str] = None,
    out_dir: str = SESSION_MEDIA_DIR,
) -> ImageAttachment:
    if not x or not y:
        raise ValueError("x/y cannot be empty")
    if len(x) != len(y):
        raise ValueError("x and y must have same length")

    _ensure_matplotlib_ready()
    _ensure_dir(out_dir)
    out_path = _media_path(out_dir, prefix="line")

    plt.figure()
    plt.plot(x, y)
    plt.title(title or "Line Chart")
    if x_label:
        plt.xlabel(x_label)
    if y_label:
        plt.ylabel(y_label)
    plt.tight_layout()
    plt.savefig(out_path, dpi=160)
    plt.close()

    return ImageAttachment(type="image", path=out_path, title=title or "Line Chart")
