"""Synthetic football match intelligence primitives."""

from .metrics import (
    METRICS_SCHEMA_VERSION,
    MatchAnalysis,
    PlayerSummary,
    SubwindowMetrics,
    WindowMetrics,
    analyze_match,
)
from .replay import EventReplay, load_match_events
from .schemas import (
    EVENT_SCHEMA_VERSION,
    INSIGHT_SCHEMA_VERSION,
    EventEnvelope,
    Insight,
    MatchEvent,
)

__all__ = [
    "EVENT_SCHEMA_VERSION",
    "INSIGHT_SCHEMA_VERSION",
    "METRICS_SCHEMA_VERSION",
    "EventEnvelope",
    "EventReplay",
    "Insight",
    "MatchAnalysis",
    "MatchEvent",
    "PlayerSummary",
    "SubwindowMetrics",
    "WindowMetrics",
    "analyze_match",
    "load_match_events",
]
