"""Sidebar: Feedback Signals demo."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("feedback_signals")

MENUS: list[Menu] = [
    m.group("feedback_signals", "Feedback signals", icon="chat-bubble-left-ellipsis", sequence=46),
    m.group("feedback_signals.overview", "Overview", parent="feedback_signals", sequence=10),
    m.item(
        "feedback_signals.home",
        "Overview",
        parent="feedback_signals.overview",
        view="home",
        sequence=10,
    ),
    m.group("feedback_signals.collect", "Collect", parent="feedback_signals", sequence=20),
    m.item(
        "feedback_signals.capture",
        "Share feedback",
        parent="feedback_signals.collect",
        href="/web/feedback_signals/capture",
        sequence=10,
        model="feedback.intake",
        perm="create",
    ),
    m.item(
        "feedback_signals.intakes",
        "Feedback intakes",
        parent="feedback_signals.collect",
        view="feedback_intake.list",
        sequence=20,
    ),
    m.group("feedback_signals.analyze", "Analyze", parent="feedback_signals", sequence=30),
    m.item(
        "feedback_signals.analytics",
        "Signal analytics",
        parent="feedback_signals.analyze",
        href="/web/feedback_signals/analytics",
        sequence=10,
        model="feedback.intake",
        perm="read",
    ),
    m.item(
        "feedback_signals.review",
        "Review signals",
        parent="feedback_signals.analyze",
        href="/web/feedback_signals/review",
        sequence=20,
        model="feedback.intake",
        perm="write",
    ),
    m.item(
        "feedback_signals.charts",
        "Tone chart",
        parent="feedback_signals.analyze",
        view="feedback_intake.graph_tone",
        sequence=30,
    ),
]
