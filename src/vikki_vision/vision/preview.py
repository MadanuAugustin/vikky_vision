"""
Live camera preview window.

All methods must be called from the main thread: macOS only allows GUI work there, and
OpenCV's HighGUI expects every window call to come from the same thread.
"""

import cv2
import numpy as np

QUIT_KEYS = {ord("q"), ord("Q"), 27}  # q or Esc
QUIT_HINT = "Press Q or close this window to quit"


def decorate(frame: np.ndarray, lines: list[str]) -> np.ndarray:
    """Mirror the frame (selfie view) and draw text lines in the top-left corner."""
    view = cv2.flip(frame, 1)
    for i, text in enumerate(line for line in lines if line):
        y = 30 + i * 28
        cv2.putText(view, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(view, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
    return view


class PreviewWindow:
    def __init__(self, title: str = "Vikki Vision"):
        self.title = title
        self._created = False
        self._seen_visible = False

    def show(self, frame: np.ndarray, lines: list[str]) -> bool:
        """Draw a frame and process window events. Returns False once the user wants to quit."""
        if not self._created:
            cv2.namedWindow(self.title, cv2.WINDOW_AUTOSIZE)
            self._created = True
        cv2.imshow(self.title, decorate(frame, lines))
        key = cv2.waitKey(1) & 0xFF
        if key in QUIT_KEYS:
            return False

        # Only treat "not visible" as closed once the window has actually been seen visible:
        # some backends report 0 / -1 until the window is mapped, or don't support the property.
        visible = cv2.getWindowProperty(self.title, cv2.WND_PROP_VISIBLE)
        if visible >= 1:
            self._seen_visible = True
        elif self._seen_visible:
            return False
        return True

    def close(self) -> None:
        if not self._created:
            return
        self._created = False
        # If the user closed the window with its X button it no longer exists, and
        # destroying it again raises "NULL window" on Windows
        if cv2.getWindowProperty(self.title, cv2.WND_PROP_VISIBLE) >= 1:
            cv2.destroyWindow(self.title)
        cv2.waitKey(1)
