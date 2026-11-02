"""
Stores each Vikki Vision session on disk:

    <root>/<YYYY-MM-DD>/<HH-MM-SS>/
        conversation.csv   timestamp, speaker, text, camera_frame
        frames/            JPEG camera frames sent to Vikki (frame_000001.jpg, ...)

`camera_frame` on each conversation row is the latest frame Vikki had seen when that line
was spoken, relative to the session folder (e.g. frames/frame_000012.jpg).
"""

import csv
import threading
from datetime import datetime
from pathlib import Path

from vikki_vision.utils.logger import get_logger

log = get_logger(__name__)

CSV_COLUMNS = ["timestamp", "speaker", "text", "camera_frame"]


class SessionRecorder:
    def __init__(self, root: Path, started_at: datetime | None = None):
        self.session_dir: Path | None = None
        self.frames_dir: Path | None = None
        self._csv_file = None
        self._csv_writer = None
        self._lock = threading.Lock()  # frames are saved from a worker thread
        self.frame_count = 0
        self.message_count = 0
        self.latest_frame = ""

        try:
            now = started_at or datetime.now()
            self.session_dir = Path(root) / now.strftime("%Y-%m-%d") / now.strftime("%H-%M-%S")
            self.frames_dir = self.session_dir / "frames"
            self.frames_dir.mkdir(parents=True, exist_ok=True)

            # utf-8-sig so Excel opens the CSV with the right encoding
            self._csv_file = open(self.session_dir / "conversation.csv", "w", newline="", encoding="utf-8-sig")
            self._csv_writer = csv.writer(self._csv_file)
            self._csv_writer.writerow(CSV_COLUMNS)
            self._csv_file.flush()
            log.info("Recording session to %s", self.session_dir)
        except Exception:
            log.exception("Could not create session folder; conversation and frames will not be saved")
            self.frames_dir = None
            self._csv_writer = None

    def save_frame(self, jpeg_bytes: bytes) -> str:
        """Write one camera frame and return its path relative to the session folder."""
        if self.frames_dir is None:
            return ""
        try:
            with self._lock:
                self.frame_count += 1
                name = f"frame_{self.frame_count:06d}.jpg"
            (self.frames_dir / name).write_bytes(jpeg_bytes)
            with self._lock:
                self.latest_frame = f"frames/{name}"
                return self.latest_frame
        except Exception:
            log.exception("Failed to save camera frame")
            return ""

    def add_message(self, speaker: str, text: str, timestamp: datetime | None = None) -> None:
        """Append one line of the conversation to conversation.csv."""
        if self._csv_writer is None or not text:
            return
        try:
            ts = (timestamp or datetime.now()).isoformat(sep=" ", timespec="seconds")
            with self._lock:
                self._csv_writer.writerow([ts, speaker, text, self.latest_frame])
                self._csv_file.flush()
                self.message_count += 1
        except Exception:
            log.exception("Failed to save conversation message")

    def close(self) -> None:
        try:
            if self._csv_file is not None:
                self._csv_file.close()
                self._csv_file = None
                self._csv_writer = None
                log.info(
                    "Saved session: %d conversation lines, %d camera frames in %s",
                    self.message_count, self.frame_count, self.session_dir,
                )
        except Exception:
            log.exception("Failed to close session recording")
