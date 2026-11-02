"""
Entry point for Vikki Vision.

    vikki-vision            (console command installed with the package)
    python -m vikki_vision

Press Ctrl+C to quit.
"""

import asyncio
from pathlib import Path

from vikki_vision.config import ConfigError, load_settings
from vikki_vision.utils.logger import get_logger, setup_logging

log = get_logger(__name__)


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as e:
        setup_logging(Path.cwd() / "logs")
        log.error("%s", e)
        return 1

    setup_logging(settings.log_dir)

    try:
        settings.validate()
        # Imported here so a missing dependency is reported through the log
        from vikki_vision.assistant.client import create_client
        from vikki_vision.assistant.session import VikkiSession

        asyncio.run(VikkiSession(settings, create_client(settings)).run())
        return 0
    except ConfigError as e:
        log.error("%s", e)
        return 1
    except ImportError as e:
        log.critical("Missing dependency: %s. Run 'pip install -e .' (or 'pip install -r requirements.txt').", e)
        return 1
    except KeyboardInterrupt:
        log.info("Interrupted with Ctrl+C")
        return 0
    except Exception:
        log.exception("Fatal error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
