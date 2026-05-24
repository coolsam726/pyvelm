"""Tests for workflow inbox helpers."""

from pyvelm.workflow.inbox import list_inbox_items


def test_inbox_empty_without_registry():
    class _Env:
        uid = 1
        registry = {}

    assert list_inbox_items(_Env()) == []
