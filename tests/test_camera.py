import threading
import time

import numpy as np
import pytest

from vikki_vision.vision import camera as camera_module
from vikki_vision.vision.camera import Camera, CameraError


class FakeCapture:
    """Stands in for cv2.VideoCapture."""

    def __init__(self, frames=None, opened=True, block=None):
        self.frames = list(frames) if frames is not None else None  # None = endless frames
        self.opened = opened
        self.block = block  # threading.Event: read() waits on it to simulate a stalled driver
        self.released = False
        self.reads_after_release = 0

    def isOpened(self):
        return self.opened

    def read(self):
        if self.released:
            self.reads_after_release += 1
        if self.block is not None:
            self.block.wait()
        time.sleep(0.005)
        if self.frames is None:
            return True, np.zeros((4, 4, 3), dtype=np.uint8)
        if self.frames:
            return True, self.frames.pop(0)
        return False, None

    def release(self):
        self.released = True


def use_capture(monkeypatch, capture):
    monkeypatch.setattr(camera_module.cv2, "VideoCapture", lambda index: capture)


def wait_for(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_open_failure_raises_and_releases(monkeypatch):
    capture = FakeCapture(opened=False)
    use_capture(monkeypatch, capture)
    with pytest.raises(CameraError):
        Camera().open()
    assert capture.released


def test_sequence_number_advances_with_new_frames(monkeypatch):
    use_capture(monkeypatch, FakeCapture())
    cam = Camera()
    cam.open()
    assert cam.latest_frame() == (0, None)
    cam.start()
    assert wait_for(lambda: cam.latest_frame()[0] >= 2)
    cam.stop()


def test_camera_failure_sets_failed_and_releases(monkeypatch):
    capture = FakeCapture(frames=[np.zeros((4, 4, 3), dtype=np.uint8)])
    use_capture(monkeypatch, capture)
    cam = Camera()
    cam.open()
    cam.start()
    assert wait_for(lambda: cam.failed)
    assert wait_for(lambda: capture.released)
    cam.stop()


def test_stop_while_opening_releases_the_device(monkeypatch):
    """Ctrl+C during startup: stop() runs before open() has finished."""
    capture = FakeCapture()
    entered, proceed = threading.Event(), threading.Event()

    def slow_video_capture(index):
        entered.set()
        proceed.wait()
        return capture

    monkeypatch.setattr(camera_module.cv2, "VideoCapture", slow_video_capture)
    cam = Camera()
    opener = threading.Thread(target=cam.open)
    opener.start()
    entered.wait()
    cam.stop()
    proceed.set()
    opener.join()
    assert capture.released
    cam.start()  # must not start reading a released device
    assert cam.latest_frame() == (0, None)


def test_stop_does_not_release_under_a_stalled_thread(monkeypatch):
    block = threading.Event()
    capture = FakeCapture(block=block)
    use_capture(monkeypatch, capture)
    monkeypatch.setattr(camera_module, "STOP_TIMEOUT_SECONDS", 0.1)
    cam = Camera()
    cam.open()
    cam.start()
    cam.stop()
    assert not capture.released  # thread still inside read()
    block.set()
    assert wait_for(lambda: capture.released)  # released by the thread once it finishes
    assert capture.reads_after_release == 0


def test_encode_jpeg_downscales(monkeypatch):
    cam = Camera(max_size=(64, 64))
    jpeg = cam.encode_jpeg(np.zeros((480, 640, 3), dtype=np.uint8))
    assert jpeg[:2] == b"\xff\xd8"  # JPEG magic
