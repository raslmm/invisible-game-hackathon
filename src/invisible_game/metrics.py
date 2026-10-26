"""Deterministic window metrics and evidence-backed tactical signals."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Mapping, Sequence

from .schemas import Insight, MatchEvent

METRICS_SCHEMA_VERSION = "match-metrics.v1"
WINDOW_SECONDS = 15 * 60
SUBWINDOW_SECONDS = 5 * 60

# Transparent normalization anchors for this synthetic event schema.
# The resulting score is a rule signal, not a calibrated probability.
_WINDOW_DANGER_REFERENCE = 6.0
_WINDOW_ENTRY_REFERENCE = 8.0
_SUBWINDOW_DANGER_REFERENCE = 2.0
_SUBWINDOW_ENTRY_REFERENCE = 3.0
_PERSISTENT_SCORE_THRESHOLD = 0.58
_SUBWINDOW_SIGNAL_THRESHOLD = 0.45
_TRANSIENT_SUBWINDOW_THRESHOLD = 0.40


@dataclass(frozen=True, slots=True)
class SubwindowMetrics:
    start_seconds: int
    end_seconds: int
    event_count: int
    dangerous_turnovers: int
    opponent_attacking_entries: int
    risk_score: float
    exposure_signal: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WindowMetrics:
    match_id: str
    subject_team: str
    window_start_seconds: int
    window_end_seconds: int
    event_count: int
    subject_event_count: int
    opponent_event_count: int
    subject_event_share: float
    subject_turnovers: int
    dangerous_turnovers: int
    opponent_attacking_entries: int
    average_event_pressure: float | None
    average_subject_recovery_speed: float | None
    average_subject_defenders_behind_ball: float | None
    average_subject_fatigue: float | None
    event_rate_per_minute: float
    risk_score: float
    risk_subwindows: int
    missing: bool
    persistent_risk: bool
    transient_spike: bool
    subwindows: tuple[SubwindowMetrics, ...]
    evidence_event_ids: tuple[str, ...]
    insight: Insight | None

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["insight"] = self.insight.to_dict() if self.insight else None
        return result


@dataclass(frozen=True, slots=True)
class PlayerSummary:
    player_id: str
    player_name: str | None
    event_count: int
    turnovers: int
    dangerous_turnovers: int
    average_event_pressure: float
    average_recovery_speed: float
    average_fatigue: float
    evidence_event_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["evidence_event_ids"] = list(self.evidence_event_ids)
        return result


@dataclass(frozen=True, slots=True)
class MatchAnalysis:
    match_id: str
    subject_team: str
    duplicate_event_ids_skipped: int
    windows: tuple[WindowMetrics, ...]
    player_summaries: tuple[PlayerSummary, ...]

    @property
    def insights(self) -> tuple[Insight, ...]:
        return tuple(window.insight for window in self.windows if window.insight is not None)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": METRICS_SCHEMA_VERSION,
            "match_id": self.match_id,
            "subject_team": self.subject_team,
            "duplicate_event_ids_skipped": self.duplicate_event_ids_skipped,
            "window_seconds": WINDOW_SECONDS,
            "subwindow_seconds": SUBWINDOW_SECONDS,
            "windows": [window.to_dict() for window in self.windows],
            "player_summaries": [player.to_dict() for player in self.player_summaries],
            "insights": [insight.to_dict() for insight in self.insights],
        }


@dataclass(slots=True)
class _WindowAccumulator:
    events: list[MatchEvent]
    subwindows: list[list[MatchEvent]]


@dataclass(slots=True)
class _PlayerAccumulator:
    events: list[MatchEvent]


def _average(values: Sequence[float]) -> float | None:
    return fmean(values) if values else None


def _risk_score(
    dangerous_turnovers: int,
    opponent_entries: int,
    subject_events: Sequence[MatchEvent],
    *,
    danger_reference: float,
    entry_reference: float,
) -> float:
    """Combine exposure, recovery, and cover into an interpretable 0-1 signal."""
    if not dangerous_turnovers and not opponent_entries and not subject_events:
        return 0.0

    recovery = _average([event.recovery_speed_index for event in subject_events])
    cover = _average([float(event.defenders_behind_ball) for event in subject_events])
    danger_component = min(dangerous_turnovers / danger_reference, 1.0)
    entry_component = min(opponent_entries / entry_reference, 1.0)
    recovery_component = 1.0 - recovery if recovery is not None else 0.0
    cover_component = (
        1.0 - min(cover / 5.0, 1.0)
        if cover is not None
        else 0.0
    )
    score = (
        0.35 * danger_component
        + 0.25 * entry_component
        + 0.20 * recovery_component
        + 0.20 * cover_component
    )
    return round(max(0.0, min(score, 1.0)), 4)


def _build_insight(
    *,
    match_id: str,
    start: int,
    end: int,
    persistent: bool,
    transient: bool,
    risk_score: float,
    active_subwindows: int,
    dangerous_turnovers: int,
    opponent_entries: int,
    average_recovery: float | None,
    average_cover: float | None,
    evidence_event_ids: tuple[str, ...],
) -> Insight | None:
    if not persistent and not transient:
        return None
    if not evidence_event_ids:
        # A finding without source events is not safe to publish.
        return None

    if persistent:
        category = "persistent_defensive_risk"
        title = "Repeated defensive exposure"
        severity = 4 if risk_score >= 0.80 else 3
        recovery_text = f"{average_recovery:.2f}" if average_recovery is not None else "unavailable"
        cover_text = f"{average_cover:.2f}" if average_cover is not None else "unavailable"
        why = (
            f"{dangerous_turnovers} dangerous turnovers and {opponent_entries} opponent "
            f"attacking entries occurred in this 15-minute window. Exposure signals "
            f"recurred in {active_subwindows} of 3 five-minute segments, with average "
            f"recovery {recovery_text} and {cover_text} defenders behind "
            "the ball. This is a synthetic rule-based signal, not a probability."
        )
    else:
        category = "transient_danger"
        title = "A dangerous moment, not yet a pattern"
        severity = 2
        why = (
            f"{dangerous_turnovers} dangerous turnover(s) and {opponent_entries} "
            f"opponent attacking entries were concentrated in a short spell. Only "
            f"{active_subwindows} of 3 five-minute segments crossed the exposure "
            "signal threshold, so this window does not establish persistent risk."
        )

    # This reflects how many subwindows support the rule; it is not calibrated
    # confidence in a real-world outcome.
    support_strength = round(min(0.95, 0.50 + 0.15 * active_subwindows), 2)
    return Insight(
        insight_id=f"{match_id}-W{start // WINDOW_SECONDS + 1}-{category}",
        match_id=match_id,
        timestamp_seconds=end,
        category=category,
        severity=severity,
        confidence=support_strength,
        title=title,
        why_it_matters=why,
        evidence_event_ids=evidence_event_ids,
        signals={
            "window_start_seconds": start,
            "window_end_seconds": end,
            "risk_score": risk_score,
            "dangerous_turnovers": dangerous_turnovers,
            "opponent_attacking_entries": opponent_entries,
            "risk_subwindows": active_subwindows,
            "average_subject_recovery_speed": average_recovery or 0.0,
            "average_subject_defenders_behind_ball": average_cover or 0.0,
        },
    )


def analyze_match(
    events: Sequence[MatchEvent],
    *,
    subject_team: str | None = None,
    player_names: Mapping[str, str] | None = None,
    match_end_seconds: int | None = None,
) -> MatchAnalysis:
    """Aggregate one match into 15-minute windows and evidence-backed signals.

    Input order does not affect results. Duplicate event IDs are suppressed using
    the earliest timestamp (stable input order breaks timestamp ties). Windows
    are half-open intervals: an event at 900 seconds belongs to the next window.
    """
    if not events:
        raise ValueError("At least one event is required to analyze a match")

    match_ids = {event.match_id for event in events}
    if len(match_ids) != 1:
        raise ValueError("Analyze exactly one match at a time")
    match_id = next(iter(match_ids))

    inferred_subject_teams = {event.team_name for event in events if event.is_subject_team}
    if subject_team is None:
        if len(inferred_subject_teams) != 1:
            raise ValueError("Could not infer exactly one subject team from the events")
        subject_team = next(iter(inferred_subject_teams))
    if not subject_team:
        raise ValueError("subject_team must not be empty")
    if inferred_subject_teams and inferred_subject_teams != {subject_team}:
        raise ValueError("subject_team does not match the event subject-team flags")
    for event in events:
        if event.is_subject_team != (event.team_name == subject_team):
            raise ValueError(
                f"Subject-team flag disagrees with team_name on event {event.event_id!r}"
            )
        if event.is_dangerous_turnover and (
            not event.is_subject_team or event.event_type.lower() != "turnover"
        ):
            raise ValueError(
                f"Dangerous-turnover flag is inconsistent on event {event.event_id!r}"
            )
        if event.is_attacking_entry and event.is_subject_team:
            raise ValueError(
                f"Attacking-entry flag is inconsistent on event {event.event_id!r}"
            )

    ordered = sorted(
        enumerate(events),
        key=lambda item: (item[1].timestamp_seconds, item[0]),
    )
    unique_events: list[MatchEvent] = []
    seen_event_ids: set[str] = set()
    duplicate_count = 0
    for _, event in ordered:
        if event.event_id in seen_event_ids:
            duplicate_count += 1
            continue
        seen_event_ids.add(event.event_id)
        unique_events.append(event)

    last_timestamp = unique_events[-1].timestamp_seconds
    if match_end_seconds is None:
        window_count = last_timestamp // WINDOW_SECONDS + 1
        match_end_seconds = window_count * WINDOW_SECONDS
    elif match_end_seconds <= 0 or match_end_seconds % WINDOW_SECONDS:
        raise ValueError(
            f"match_end_seconds must be a positive multiple of {WINDOW_SECONDS}"
        )
    if last_timestamp >= match_end_seconds:
        raise ValueError("An event timestamp must be earlier than match_end_seconds")

    window_starts = range(0, match_end_seconds, WINDOW_SECONDS)
    accumulators = {
        start: _WindowAccumulator(
            events=[],
            subwindows=[[], [], []],
        )
        for start in window_starts
    }
    for event in unique_events:
        start = event.timestamp_seconds // WINDOW_SECONDS * WINDOW_SECONDS
        accumulator = accumulators[start]
        accumulator.events.append(event)
        segment_index = (event.timestamp_seconds - start) // SUBWINDOW_SECONDS
        accumulator.subwindows[segment_index].append(event)

    windows: list[WindowMetrics] = []
    player_accumulators: dict[str, _PlayerAccumulator] = {}
    for event in unique_events:
        if event.is_subject_team:
            player_accumulators.setdefault(
                event.player_id,
                _PlayerAccumulator(events=[]),
            ).events.append(event)

    for start, accumulator in accumulators.items():
        end = start + WINDOW_SECONDS
        window_events = accumulator.events
        subject_events = [event for event in window_events if event.is_subject_team]
        opponent_events = [event for event in window_events if not event.is_subject_team]
        dangerous_turnovers = sum(event.is_dangerous_turnover for event in window_events)
        opponent_entries = sum(event.is_attacking_entry for event in window_events)
        subject_turnovers = sum(
            event.event_type.lower() == "turnover" for event in subject_events
        )

        subwindow_metrics: list[SubwindowMetrics] = []
        for index, segment_events in enumerate(accumulator.subwindows):
            segment_start = start + index * SUBWINDOW_SECONDS
            segment_end = segment_start + SUBWINDOW_SECONDS
            segment_danger = sum(
                event.is_dangerous_turnover for event in segment_events
            )
            segment_entries = sum(event.is_attacking_entry for event in segment_events)
            segment_subject = [
                event for event in segment_events if event.is_subject_team
            ]
            segment_score = _risk_score(
                segment_danger,
                segment_entries,
                segment_subject,
                danger_reference=_SUBWINDOW_DANGER_REFERENCE,
                entry_reference=_SUBWINDOW_ENTRY_REFERENCE,
            )
            subwindow_metrics.append(
                SubwindowMetrics(
                    start_seconds=segment_start,
                    end_seconds=segment_end,
                    event_count=len(segment_events),
                    dangerous_turnovers=segment_danger,
                    opponent_attacking_entries=segment_entries,
                    risk_score=segment_score,
                    exposure_signal=(
                        bool(segment_events)
                        and segment_score >= _SUBWINDOW_SIGNAL_THRESHOLD
                    ),
                )
            )

        average_recovery = _average(
            [event.recovery_speed_index for event in subject_events]
        )
        average_cover = _average(
            [float(event.defenders_behind_ball) for event in subject_events]
        )
        risk_score = _risk_score(
            dangerous_turnovers,
            opponent_entries,
            subject_events,
            danger_reference=_WINDOW_DANGER_REFERENCE,
            entry_reference=_WINDOW_ENTRY_REFERENCE,
        )
        risk_subwindows = sum(item.exposure_signal for item in subwindow_metrics)
        dangerous_subwindows = sum(item.dangerous_turnovers > 0 for item in subwindow_metrics)
        persistent = (
            risk_score >= _PERSISTENT_SCORE_THRESHOLD
            and risk_subwindows >= 2
        )
        max_segment_score = max(
            (item.risk_score for item in subwindow_metrics),
            default=0.0,
        )
        transient = (
            not persistent
            and 1 <= dangerous_turnovers <= 2
            and opponent_entries >= 5
            and risk_subwindows <= 1
            and dangerous_subwindows == 1
            and max_segment_score >= _TRANSIENT_SUBWINDOW_THRESHOLD
        )
        evidence_ids = tuple(
            event.event_id
            for event in window_events
            if event.is_dangerous_turnover or event.is_attacking_entry
        )
        insight = _build_insight(
            match_id=match_id,
            start=start,
            end=end,
            persistent=persistent,
            transient=transient,
            risk_score=risk_score,
            active_subwindows=risk_subwindows,
            dangerous_turnovers=dangerous_turnovers,
            opponent_entries=opponent_entries,
            average_recovery=average_recovery,
            average_cover=average_cover,
            evidence_event_ids=evidence_ids,
        )
        windows.append(
            WindowMetrics(
                match_id=match_id,
                subject_team=subject_team,
                window_start_seconds=start,
                window_end_seconds=end,
                event_count=len(window_events),
                subject_event_count=len(subject_events),
                opponent_event_count=len(opponent_events),
                subject_event_share=(
                    len(subject_events) / len(window_events)
                    if window_events
                    else 0.0
                ),
                subject_turnovers=subject_turnovers,
                dangerous_turnovers=dangerous_turnovers,
                opponent_attacking_entries=opponent_entries,
                average_event_pressure=_average(
                    [event.pressure_intensity for event in window_events]
                ),
                average_subject_recovery_speed=average_recovery,
                average_subject_defenders_behind_ball=average_cover,
                average_subject_fatigue=_average(
                    [event.fatigue_index for event in subject_events]
                ),
                event_rate_per_minute=len(window_events) / (WINDOW_SECONDS / 60),
                risk_score=risk_score,
                risk_subwindows=risk_subwindows,
                missing=not window_events,
                persistent_risk=persistent,
                transient_spike=transient,
                subwindows=tuple(subwindow_metrics),
                evidence_event_ids=evidence_ids,
                insight=insight,
            )
        )

    player_summaries: list[PlayerSummary] = []
    names = player_names or {}
    for player_id, accumulator in player_accumulators.items():
        player_events = accumulator.events
        player_summaries.append(
            PlayerSummary(
                player_id=player_id,
                player_name=names.get(player_id),
                event_count=len(player_events),
                turnovers=sum(
                    event.event_type.lower() == "turnover" for event in player_events
                ),
                dangerous_turnovers=sum(
                    event.is_dangerous_turnover for event in player_events
                ),
                average_event_pressure=fmean(
                    event.pressure_intensity for event in player_events
                ),
                average_recovery_speed=fmean(
                    event.recovery_speed_index for event in player_events
                ),
                average_fatigue=fmean(
                    event.fatigue_index for event in player_events
                ),
                evidence_event_ids=tuple(
                    event.event_id
                    for event in player_events
                    if event.is_dangerous_turnover
                ),
            )
        )
    player_summaries.sort(
        key=lambda player: (
            -player.dangerous_turnovers,
            -player.turnovers,
            -player.event_count,
            player.player_name or player.player_id,
        )
    )

    return MatchAnalysis(
        match_id=match_id,
        subject_team=subject_team,
        duplicate_event_ids_skipped=duplicate_count,
        windows=tuple(windows),
        player_summaries=tuple(player_summaries),
    )
