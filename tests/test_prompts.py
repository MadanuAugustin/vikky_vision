from vikki_vision.assistant.prompts import build_system_instruction


def test_instruction_uses_assistant_name():
    text = build_system_instruction("Vikki")
    assert "Your name is Vikki" in text
    assert "Hi Vikki" in text


def test_instruction_does_not_name_the_underlying_model():
    text = build_system_instruction("Vikki").lower()
    assert "gemini" not in text
    assert "google" not in text
