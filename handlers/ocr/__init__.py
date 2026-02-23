from __future__ import annotations


def run_ocr(*args, **kwargs):
    from handlers.ocr.pipeline import run_ocr as _run_ocr

    return _run_ocr(*args, **kwargs)


__all__ = ["run_ocr"]
