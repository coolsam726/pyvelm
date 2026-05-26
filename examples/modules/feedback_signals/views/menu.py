"""Sidebar: Feedback Signals demo."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("feedback_signals")

MENUS: list[Menu] = [
    m.group("feedback_signals", "Feedback signals", icon="chat-bubble-left-ellipsis", sequence=46),
    m.item(
        "feedback_signals.home",
        "Overview",
        parent="feedback_signals",
        view="home",
        sequence=1,
    ),
    m.item(
        "feedback_signals.capture",
        "Share feedback",
        parent="feedback_signals",
        href="/web/feedback_signals/capture",
        sequence=5,
        model="feedback.intake",
        perm="create",
    ),
    m.item(
        "feedback_signals.analytics",
        "Signal analytics",
        parent="feedback_signals",
        href="/web/feedback_signals/analytics",
        sequence=8,
        model="feedback.intake",
        perm="read",
    ),
    m.item(
        "feedback_signals.review",
        "Review signals",
        parent="feedback_signals",
        href="/web/feedback_signals/review",
        sequence=9,
        model="feedback.intake",
        perm="write",
    ),
    m.item(
        "feedback_signals.intakes",
        "Feedback intakes",
        parent="feedback_signals",
        view="feedback_intake.list",
        sequence=10,
    ),
    m.item(
        "feedback_signals.charts",
        "Tone chart",
        parent="feedback_signals",
        view="feedback_intake.graph_tone",
        sequence=20,
    ),
]
