"""Tests for Ollama provider wiring."""

import os

from feedback_signals.llm_analysis import (
    ollama_chat_url,
    resolve_provider,
)


def setup_function():
    for key in (
        "LLM_PROVIDER",
        "OPENROUTER_API_KEY",
        "OLLAMA_DISABLED",
    ):
        os.environ.pop(key, None)


def test_resolve_provider_ollama_explicit():
    os.environ["LLM_PROVIDER"] = "ollama"
    assert resolve_provider() == "ollama"


def test_resolve_provider_openrouter_when_keyed():
    os.environ["LLM_PROVIDER"] = "openrouter"
    os.environ["OPENROUTER_API_KEY"] = "sk-test"
    assert resolve_provider() == "openrouter"


def test_resolve_provider_auto_ollama_without_openrouter_key():
    assert resolve_provider() == "ollama"


def test_resolve_provider_auto_openrouter_with_key():
    os.environ["OPENROUTER_API_KEY"] = "sk-test"
    assert resolve_provider() == "openrouter"


def test_ollama_chat_url_normalizes_base():
    os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"
    assert ollama_chat_url() == "http://127.0.0.1:11434/v1/chat/completions"
    os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434/v1"
    assert ollama_chat_url() == "http://127.0.0.1:11434/v1/chat/completions"
