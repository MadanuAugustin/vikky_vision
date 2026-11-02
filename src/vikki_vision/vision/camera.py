"""Webcam capture, producing JPEG frames."""

import io

import cv2
import PIL.Image

from vikki_vision.utils.logger import get_logger

log = get_logger(__name__)

MAX_FRAME_SIZE = (1024, 1024)


class Camera:
    def __init__(self, index: int = 0, max_size: tuple[int, int] = MAX_FRAME_SIZE):
        self.index = index
        self.max_size = max_size
        self._capture: cv2.VideoCapture | None = None

    def open(self) -> None:
        """Open the camera (blocking; can take a few seconds)."""
        self._capture = cv2.VideoCapture(self.index)
        if not self._capture.isOpened():
            raise RuntimeError(f"Could not open camera {self.index}")
        log.info("Camera %d opened", self.index)

    def read_jpeg(self) -> bytes | None:
        """Capture one frame as JPEG bytes, or None if the camera returned no frame."""
        ret, frame = self._capture.read()
        if not ret:
            return None
        # OpenCV captures in BGR but PIL expects RGB
        img = PIL.Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        img.thumbnail(self.max_size)
        buf = io.BytesIO()
        img.save(buf, format="jpeg")
        return buf.getvalue()

    def release(self) -> None:
        try:
            if self._capture is not None:
                self._capture.release()
                self._capture = None
                log.info("Camera released")
        except Exception:
            log.exception("Error releasing camera")
