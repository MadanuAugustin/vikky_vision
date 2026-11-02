"""
Webcam capture with an optional live preview window.

A background thread reads the camera continuously, so the preview runs at the camera's full
frame rate, while the session picks up the latest frame (as JPEG) at its own, slower pace.
All OpenCV window calls happen on that one thread, as HighGUI requires.
"""

import io
import threading
from typing import Callable

import cv2
import PIL.Image

from vikki_vision.utils.logger import get_logger

log = get_logger(__name__)

MAX_FRAME_SIZE = (1024, 1024)
QUIT_KEYS = {ord("q"), ord("Q"), 27}  # q or Esc


class Camera:
    def __init__(
        self,
        index: int = 0,
        max_size: tuple[int, int] = MAX_FRAME_SIZE,
        show_preview: bool = True,
        window_title: str = "Vikki Vision",
    ):
        self.index = index
        self.max_size = max_size
        self.show_preview = show_preview
        self.window_title = window_title

        self.user_closed = False   # user closed the preview window or pressed q/Esc
        self.failed = False        # camera stopped delivering frames

        self._capture: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest_frame = None
        self._status_text: Callable[[], str] | None = None

    def open(self) -> None:
        """Open the camera (blocking; can take a few seconds)."""
        self._capture = cv2.VideoCapture(self.index)
        if not self._capture.isOpened():
            raise RuntimeError(f"Could not open camera {self.index}")
        log.info("Camera %d opened", self.index)

    def start(self, status_text: Callable[[], str] | None = None) -> None:
        """Start reading frames (and showing the preview) in a background thread."""
        self._status_text = status_text
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        window_shown = False
        try:
            while not self._stop.is_set():
                ret, frame = self._capture.read()
                if not ret:
                    log.warning("Camera returned no frame")
                    self.failed = True
                    break
                with self._lock:
                    self._latest_frame = frame

                if not self.show_preview:
                    continue
                cv2.imshow(self.window_title, self._decorate(frame))
                window_shown = True
                key = cv2.waitKey(1) & 0xFF
                window_open = cv2.getWindowProperty(self.window_title, cv2.WND_PROP_VISIBLE) >= 1
                if key in QUIT_KEYS or not window_open:
                    log.info("Preview window closed by the user")
                    self.user_closed = True
                    break
        except Exception:
            log.exception("Camera thread failed")
            self.failed = True
        finally:
            if window_shown:
                try:
                    cv2.destroyWindow(self.window_title)
                    cv2.waitKey(1)
                except Exception:
                    log.exception("Error closing preview window")

    def _decorate(self, frame):
        """Mirror the frame (selfie view) and draw the status line. Only used for the preview."""
        view = cv2.flip(frame, 1)
        status = self._status_text() if self._status_text else ""
        lines = [status, "Press Q or close this window to quit"]
        for i, text in enumerate(line for line in lines if line):
            y = 30 + i * 28
            cv2.putText(view, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(view, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
        return view

    def latest_jpeg(self) -> bytes | None:
        """The most recent frame as JPEG bytes (not mirrored), or None if none captured yet."""
        with self._lock:
            frame = self._latest_frame
        if frame is None:
            return None
        # OpenCV captures in BGR but PIL expects RGB
        img = PIL.Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        img.thumbnail(self.max_size)
        buf = io.BytesIO()
        img.save(buf, format="jpeg")
        return buf.getvalue()

    def stop(self) -> None:
        """Stop the background thread, close the preview and release the camera."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        try:
            if self._capture is not None:
                self._capture.release()
                self._capture = None
                log.info("Camera released")
        except Exception:
            log.exception("Error releasing camera")
