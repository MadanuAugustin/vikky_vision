import numpy as np
import pytest

from vikki_vision.vision import preview as preview_module
from vikki_vision.vision.preview import PreviewWindow, decorate

FRAME = np.zeros((40, 60, 3), dtype=np.uint8)


class FakeHighGui:
    def __init__(self, monkeypatch, visible, keys=None):
        self.visible = list(visible)
        self.keys = list(keys or [])
        self.destroyed = False
        cv2 = preview_module.cv2
        monkeypatch.setattr(cv2, "namedWindow", lambda *a: None)
        monkeypatch.setattr(cv2, "imshow", lambda *a: None)
        monkeypatch.setattr(cv2, "waitKey", lambda *a: self.keys.pop(0) if self.keys else -1)
        monkeypatch.setattr(cv2, "getWindowProperty", lambda *a: self.visible.pop(0) if self.visible else 1.0)
        monkeypatch.setattr(cv2, "destroyWindow", lambda *a: setattr(self, "destroyed", True))


def test_not_yet_visible_window_is_not_treated_as_closed(monkeypatch):
    # Some backends report 0 or -1 until the window is mapped
    FakeHighGui(monkeypatch, visible=[0.0, -1.0, 0.0, 1.0])
    window = PreviewWindow()
    assert all(window.show(FRAME, []) for _ in range(4))


def test_unsupported_visibility_property_never_closes(monkeypatch):
    FakeHighGui(monkeypatch, visible=[-1.0] * 10)
    window = PreviewWindow()
    assert all(window.show(FRAME, []) for _ in range(10))


def test_closing_a_visible_window_quits(monkeypatch):
    FakeHighGui(monkeypatch, visible=[1.0, 1.0, 0.0])
    window = PreviewWindow()
    assert [window.show(FRAME, []) for _ in range(3)] == [True, True, False]


@pytest.mark.parametrize("key", [ord("q"), ord("Q"), 27])
def test_quit_keys(monkeypatch, key):
    FakeHighGui(monkeypatch, visible=[1.0], keys=[key])
    assert PreviewWindow().show(FRAME, []) is False


def test_close_destroys_window_only_if_created(monkeypatch):
    gui = FakeHighGui(monkeypatch, visible=[1.0])
    window = PreviewWindow()
    window.close()
    assert not gui.destroyed
    window.show(FRAME, [])
    window.close()
    assert gui.destroyed


def test_decorate_mirrors_without_changing_the_original():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    frame[:, 0] = 255  # white left column
    view = decorate(frame, [])
    assert view[:, -1].min() == 255  # now on the right
    assert frame[:, 0].min() == 255 and frame[:, -1].max() == 0


def test_close_skips_destroy_when_user_already_closed_it(monkeypatch):
    gui = FakeHighGui(monkeypatch, visible=[1.0, 0.0, 0.0])
    window = PreviewWindow()
    window.show(FRAME, [])
    assert window.show(FRAME, []) is False
    window.close()
    assert not gui.destroyed
