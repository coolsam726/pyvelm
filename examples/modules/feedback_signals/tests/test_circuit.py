"""Circuit breaker tests for OpenRouter backoff."""

import time

from feedback_signals import llm_circuit as circuit


def setup_function():
    circuit.reset()


def test_circuit_opens_and_skips():
    circuit.trip("429 test", seconds=30)
    assert circuit.is_circuit_open()
    assert circuit.should_skip_llm()
    assert circuit.should_skip_llm()


def test_circuit_closes_after_backoff():
    circuit.trip("test", seconds=5.0)
    assert circuit.is_circuit_open()
    time.sleep(5.05)
    assert not circuit.is_circuit_open()
    assert not circuit.should_skip_llm()


def test_success_resets_streak():
    circuit.trip("fail", seconds=60)
    assert circuit.is_circuit_open()
    circuit.reset()
    assert not circuit.is_circuit_open()
