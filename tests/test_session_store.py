import csv
from datetime import datetime

from vikki_vision.storage.session_store import CSV_COLUMNS, SessionRecorder


def read_rows(recorder):
    with open(recorder.session_dir / "conversation.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def test_creates_dated_session_folder(tmp_path):
    recorder = SessionRecorder(tmp_path, started_at=datetime(2026, 11, 2, 10, 20, 42))
    assert recorder.session_dir == tmp_path / "2026-11-02" / "10-20-42"
    assert (recorder.session_dir / "frames").is_dir()
    recorder.close()


def test_messages_link_to_latest_frame(tmp_path):
    recorder = SessionRecorder(tmp_path)
    recorder.add_message("User", "Hello")
    assert recorder.save_frame(b"jpeg-1") == "frames/frame_000001.jpg"
    recorder.add_message("Vikki", "Hi, I'm Vikki", datetime(2026, 11, 2, 10, 21, 0))
    recorder.close()

    rows = read_rows(recorder)
    assert rows[0] == CSV_COLUMNS
    assert rows[1][1:] == ["User", "Hello", ""]
    assert rows[2] == ["2026-11-02 10:21:00", "Vikki", "Hi, I'm Vikki", "frames/frame_000001.jpg"]
    assert (recorder.session_dir / "frames" / "frame_000001.jpg").read_bytes() == b"jpeg-1"


def test_empty_messages_are_skipped(tmp_path):
    recorder = SessionRecorder(tmp_path)
    recorder.add_message("User", "")
    recorder.close()
    assert len(read_rows(recorder)) == 1
    assert recorder.message_count == 0


def test_writes_after_close_are_ignored(tmp_path):
    recorder = SessionRecorder(tmp_path)
    recorder.close()
    recorder.add_message("User", "too late")
    assert len(read_rows(recorder)) == 1
