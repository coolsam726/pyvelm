"""Sidebar: Feedback Signals demo."""

from pyvelm.builders import Menus, ViewsData

m = Menus("feedback_signals")

views_data = (
    ViewsData.make()
    .menus(
        m.group(
            "feedback_signals",
            "Feedback signals",
            icon="chat-bubble-left-ellipsis",
            sequence=46,
        ).children(
            [
                m.group("feedback_signals.overview", "Overview", sequence=10).children(
                    [
                        m.item(
                            "feedback_signals.home",
                            "Overview",
                            view="home",
                            sequence=10,
                        ),
                    ]
                ),
                m.group("feedback_signals.collect", "Collect", sequence=20).children(
                    [
                        m.item(
                            "feedback_signals.capture",
                            "Share feedback",
                            href="/web/feedback_signals/capture",
                            sequence=10,
                            model="feedback.intake",
                            perm="create",
                        ),
                        m.item(
                            "feedback_signals.intakes",
                            "Feedback intakes",
                            view="feedback_intake.list",
                            sequence=20,
                        ),
                    ]
                ),
                m.group("feedback_signals.analyze", "Analyze", sequence=30).children(
                    [
                        m.item(
                            "feedback_signals.analytics",
                            "Signal analytics",
                            href="/web/feedback_signals/analytics",
                            sequence=10,
                            model="feedback.intake",
                            perm="read",
                        ),
                        m.item(
                            "feedback_signals.review",
                            "Review signals",
                            href="/web/feedback_signals/review",
                            sequence=20,
                            model="feedback.intake",
                            perm="write",
                        ),
                        m.item(
                            "feedback_signals.charts",
                            "Tone chart",
                            view="feedback_intake.graph_tone",
                            sequence=30,
                        ),
                    ]
                ),
            ]
        ),
    )
)
