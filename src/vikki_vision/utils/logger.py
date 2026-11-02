"""
Logging setup for Vikki Vision.

Each run writes to its own file under <log_dir>/<YYYY-MM-DD>/vikki_vision_<HH-MM-SS>.log,
and also echoes INFO+ messages to the console. Logs contain technical events only;
conversation content is stored separately by `storage.session_store`.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT_LOGGER_NAME = "vikki_vision"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"
CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"


def setup_logging(log_dir: Path) -> Path | None:
    """Attach file + console handlers to the package logger. Returns the log file path."""
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT, "%H:%M:%S"))
    root.addHandler(console_handler)

    try:
        now = datetime.now()
        dated_dir = Path(log_dir) / now.strftime("%Y-%m-%d")
        dated_dir.mkdir(parents=True, exist_ok=True)
        log_file = dated_dir / f"vikki_vision_{now.strftime('%H-%M-%S')}.log"

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(file_handler)

        root.debug("Logging initialised, writing to %s", log_file)
        return log_file
    except Exception as e:
        # Console logging still works, so the app can keep running
        root.error("Failed to set up file logging: %s", e)
        return None


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the package logger, e.g. get_logger(__name__)."""
    if name == ROOT_LOGGER_NAME or name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
