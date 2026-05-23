"""Declarative feedback dashboard — KPIs, charts, and recent intakes.

Open at ``/web/views/feedback_signals/home`` after Apps → Sync.
"""

from pyvelm.builders import (
    chart_widget,
    dashboard_view,
    link_widget,
    stat_widget,
    table_widget,
)
from pyvelm.types import View

VIEWS: list[View] = [
    dashboard_view(
        "home",
        title="Feedback overview",
        subtitle="Live roll-up from feedback.intake — charts reuse graph views.",
        columns=4,
        widgets=[
            stat_widget(
                "total_intakes",
                title="Total stories",
                model="feedback.intake",
                domain=[("active", "=", True)],
                href="/web/views/feedback_signals/feedback_intake.list",
            ),
            stat_widget(
                "pending_review",
                title="Awaiting verification",
                model="feedback.intake",
                domain=[
                    ("active", "=", True),
                    ("signals_verified", "=", False),
                ],
                href="/web/feedback_signals/review",
            ),
            stat_widget(
                "verified",
                title="Verified signals",
                model="feedback.intake",
                domain=[("signals_verified", "=", True)],
            ),
            stat_widget(
                "all_intakes",
                title="All intakes",
                model="feedback.intake",
                domain=[("active", "=", True)],
                href="/web/feedback_signals/feedback_intake.list",
            ),
            chart_widget(
                "tone_pie",
                title="Stories by tone",
                view="feedback_intake.graph_tone",
                colspan=2,
            ),
            chart_widget(
                "surface_mood",
                title="Avg mood noise by surface",
                view="feedback_intake.graph_surface",
                colspan=2,
            ),
            table_widget(
                "recent_intakes",
                title="Latest intakes",
                view="feedback_intake.list",
                columns=[
                    "surface",
                    # "insight_summary",
                    "tone_label",
                    "sentiment_readout",
                    "signals_verified",
                ],
                domain=[("active", "=", True)],
                colspan="full",
                limit=6,
                order="id DESC",
                more_href="/web/views/feedback_signals/feedback_intake.list",
            ),
            link_widget(
                "capture",
                title="Share feedback",
                subtitle="Capture",
                description="Open the narrative-first intake form for a new story.",
                url="/web/feedback_signals/capture",
            ),
            link_widget(
                "review",
                title="Review signals",
                subtitle="Human verification",
                description="Confirm or correct LLM-derived tone, topics, and sentiment.",
                url="/web/feedback_signals/review",
            ),
            link_widget(
                "analytics",
                title="Signal analytics",
                subtitle="Roll-up",
                description="KPI cards and breakdowns from the analytics pipeline.",
                url="/web/feedback_signals/analytics",
            ),
        ],
    ),
]
