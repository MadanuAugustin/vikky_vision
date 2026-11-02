"""
Webcam capture.

A background thread reads the camera continuously and keeps the latest frame, so the preview
window can run at the camera's full frame rate while the session sends frames at its own,
slower pace. This module does no window/GUI work: the preview (vision/preview.py) is drawn
from the main thread, which macOS requires.
"""

import io
import threading

import cv2
import numpy as np
import PIL.Image

from vikki_vision.utils.logger import get_logger

log = get_logger(__name__)

MAX_FRAME_SIZE = (1024, 1024)
STOP_TIMEOUT_SECONDS = 5


class CameraError(RuntimeError):
    """The camera could not be opened or stopped delivering frames."""


class Camera:
    def __init__(self, index: int = 0, max_size: tuple[int, int] = MAX_FRAME_SIZE):
        self.index = index
        self.max_size = max_size
        self.failed = False  # set when the camera stops delivering frames

        self._capture: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._seq = 0  # increments with every new frame, so callers can skip frames they've seen

    def open(self) -> None:
        """Open the camera (blocking; can take a few seconds)."""
        capture = cv2.VideoCapture(self.index)
        if not capture.isOpened():
            capture.release()
            raise CameraError(f"Could not open camera {self.index}")
        with self._lock:
            if self._stop.is_set():
                # stop() was called while we were still opening (e.g. Ctrl+C during startup)
                capture.release()
                log.info("Camera %d released (shutdown requested while opening)", self.index)
                return
            self._capture = capture
        log.info("Camera %d opened", self.index)

    def start(self) -> None:
        """Start reading frames in a background thread."""
        with self._lock:
            if self._capture is None or self._stop.is_set():
                return
            self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                ret, frame = self._capture.read()
                if not ret:
                    log.warning("Camera returned no frame")
                    self.failed = True
                    break
                with self._lock:
                    self._frame = frame
                    self._seq += 1
        except Exception:
            log.exception("Camera capture failed")
            self.failed = True
        finally:
            # The capture thread owns the device while it runs, so it is the one that releases it
            self._release()

    def latest_frame(self) -> tuple[int, np.ndarray | None]:
        """(sequence number, frame) of the most recent frame; frame is None until the first one."""
        with self._lock:
            return self._seq, self._frame

    def encode_jpeg(self, frame: np.ndarray) -> bytes:
        """Encode a captured (BGR) frame as JPEG, downscaled to max_size."""
        # OpenCV captures in BGR but PIL expects RGB
        img = PIL.Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        img.thumbnail(self.max_size)
        buf = io.BytesIO()
        img.save(buf, format="jpeg")
        return buf.getvalue()

    def _release(self) -> None:
        with self._lock:
            capture, self._capture = self._capture, None
        if capture is None:
            return
        try:
            capture.release()
            log.info("Camera released")
        except Exception:
            log.exception("Error releasing camera")

    def stop(self) -> None:
        """Stop capturing and release the camera."""
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is None:
            self._release()  # opened but never started, or never opened
            return
        thread.join(timeout=STOP_TIMEOUT_SECONDS)
        if thread.is_alive():
            # Don't release the device under a thread that's still using it; it releases on exit
            log.warning("Camera thread did not stop within %d s; it will release the camera when it finishes",
                        STOP_TIMEOUT_SECONDS)
