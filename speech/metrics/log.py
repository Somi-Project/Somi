import logging
import os
from speech.config import LOG_PATH

os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logger = logging.getLogger("speech")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
