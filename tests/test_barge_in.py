import numpy as np

from vikki_vision.audio.barge_in import BargeInDetector, rms


def test_rms_of_silence_is_zero():
    assert rms(np.zeros(1024, dtype=np.int16).tobytes()) == 0.0


def test_rms_of_constant_signal():
    assert rms(np.full(1024, 1000, dtype=np.int16).tobytes()) == 1000.0


def test_rms_of_empty_buffer():
    assert rms(b"") == 0.0


def test_quiet_echo_never_triggers():
    detector = BargeInDetector(min_rms=600)
    assert not any(detector.update(50) for _ in range(100))


def test_sustained_loud_speech_triggers():
    detector = BargeInDetector(min_rms=600, trigger_chunks=3)
    assert [detector.update(2000) for _ in range(3)] == [False, False, True]


def test_single_spike_does_not_trigger():
    detector = BargeInDetector(min_rms=600, trigger_chunks=3)
    results = [detector.update(level) for level in (2000, 50, 2000, 50, 2000, 50)]
    assert not any(results)


def test_threshold_rises_with_loud_echo():
    detector = BargeInDetector(min_rms=600, echo_factor=1.5)
    detector.update(500)  # below threshold, so treated as echo
    assert detector.threshold == 750


def test_reset_clears_partial_detection():
    detector = BargeInDetector(min_rms=600, trigger_chunks=3)
    detector.update(2000)
    detector.update(2000)
    detector.reset()
    assert not detector.update(2000)
