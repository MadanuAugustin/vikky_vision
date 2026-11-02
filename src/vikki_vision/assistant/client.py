"""Creates the API client and the live session configuration."""

from google import genai
from google.genai import types

from vikki_vision.assistant.prompts import build_system_instruction
from vikki_vision.config import Settings


def create_client(settings: Settings) -> genai.Client:
    return genai.Client(http_options={"api_version": "v1beta"}, api_key=settings.api_key)


def build_live_config(settings: Settings) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        system_instruction=build_system_instruction(settings.assistant_name),
        response_modalities=["AUDIO"],
        # Transcripts of both sides are used to record the conversation
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        media_resolution="MEDIA_RESOLUTION_MEDIUM",
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.voice_name)
            )
        ),
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=104857,
            sliding_window=types.SlidingWindow(target_tokens=52428),
        ),
    )
