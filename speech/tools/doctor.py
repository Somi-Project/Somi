from __future__ import annotations

import json

from speech.doctor import run_speech_doctor


def main() -> None:
    report = run_speech_doctor()
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
