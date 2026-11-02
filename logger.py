"""
Logging setup for Vikki Vision.

Each run writes to its own file under logs/<YYYY-MM-DD>/vikki_vision_<HH-MM-SS>.log,
and also echoes INFO+ messages to the console.
"""

import logging
import os
import sys
from datetime import datetime

LOG_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s"

_configured = False


def _configure_root():
    """Create the dated log folder and attach file + console handlers once per process."""
    global _configured
    if _configured:
        return

    try:
        now = datetime.now()
        log_dir = os.path.join(LOG_ROOT, now.strftime("%Y-%m-%d"))
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"vikki_vision_{now.strftime('%H-%M-%S')}.log")

        root = logging.getLogger("vikki_vision")
        root.setLevel(logging.DEBUG)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(file_handler)

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%H:%M:%S"))
        root.addHandler(console_handler)

        root.debug("Logging initialised, writing to %s", log_file)
    except Exception as e:
        # Fall back to console-only logging so the app can still run
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
        logging.getLogger("vikki_vision").error("Failed to set up file logging: %s", e)
    finally:
        _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a child logger of the 'vikki_vision' logger, e.g. get_logger(__name__)."""
    _configure_root()
    return logging.getLogger(f"vikki_vision.{name}")
