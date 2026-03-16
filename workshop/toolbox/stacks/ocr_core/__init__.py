from __future__ import annotations


def run_ocr(*args, **kwargs):
    from workshop.toolbox.stacks.ocr_core.pipeline import run_ocr as _run_ocr

    return _run_ocr(*args, **kwargs)


__all__ = ["run_ocr"]

