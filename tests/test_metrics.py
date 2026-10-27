"""Boundary and evidence checks for deterministic match metrics."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from invisible_game import MatchEvent, analyze_match


SUBJECT = "Northbridge FC"
OPPONENT = "Eastport United"


def event(
    event_id: str,
    timestamp: int,
    *,
    subject: bool = True,
    event_type: str = "pass",
    dangerous: bool = False,
    entry: bool = False,
    recovery: float = 0.75,
    defenders: int = 4,
    player_id: str = "P0001",
) -> MatchEvent:
    return MatchEvent(
        event_id=event_id,
        match_id="TEST001",
        timestamp_seconds=timestamp,
        minute=timestamp // 60,
        period=1 if timestamp < 2700 else 2,
        team_name=SUBJECT if subject else OPPONENT,
        player_id=player_id,
        player_position="CM",
        event_type=event_type,
        outcome="won" if event_type == "turnover" else "successful",
        possession_id=f"POS-{timestamp // 300}",
        x=50.0,
        y=50.0,
        pitch_zone="middle_third",
        pitch_lane="central",
        pressure_intensity=0.5,
        defenders_behind_ball=defenders,
        recovery_speed_index=recovery,
        fatigue_index=0.2,
        xg=None,
        is_subject_team=subject,
        data_origin="fully_synthetic",
        is_dangerous_turnover=dangerous,
        is_attacking_entry=entry,
    )


class MatchMetricsTests(unittest.TestCase):
    def test_windows_use_half_open_boundaries(self) -> None:
        result = analyze_match(
            [
                event("E899", 899),
                event("E900", 900),
            ],
            match_end_seconds=1800,
        )
        self.assertEqual([window.window_start_seconds for window in result.windows], [0, 900])
        self.assertEqual([window.event_count for window in result.windows], [1, 1])

    def test_timestamp_at_explicit_match_end_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            analyze_match([event("AT_END", 1800)], match_end_seconds=1800)

    def test_out_of_order_input_is_sorted_and_duplicates_are_suppressed(self) -> None:
        first = event("DANGER", 120, event_type="turnover", dangerous=True)
        second = event("ENTRY", 150, subject=False, entry=True)
        result = analyze_match([second, first, first])
        window = result.windows[0]
        self.assertEqual(result.duplicate_event_ids_skipped, 1)
        self.assertEqual(window.event_count, 2)
        self.assertEqual(window.evidence_event_ids, ("DANGER", "ENTRY"))

    def test_missing_window_is_present_and_has_no_invented_averages(self) -> None:
        result = analyze_match(
            [event("START", 5), event("LATE", 1805)],
            match_end_seconds=2700,
        )
        missing = result.windows[1]
        self.assertEqual(len(result.windows), 3)
        self.assertTrue(missing.missing)
        self.assertEqual(missing.event_count, 0)
        self.assertEqual(missing.risk_score, 0)
        self.assertIsNone(missing.average_subject_recovery_speed)
        self.assertIsNone(missing.insight)

    def test_repeated_risk_has_recurrence_and_valid_evidence_references(self) -> None:
        events: list[MatchEvent] = []
        for segment in range(3):
            start = segment * 300
            events.extend(
                [
                    event(
                        f"D{segment}",
                        start + 10,
                        event_type="turnover",
                        dangerous=True,
                        recovery=0.3,
                        defenders=2,
                    ),
                    event(
                        f"A{segment}",
                        start + 30,
                        subject=False,
                        entry=True,
                    ),
                    event(
                        f"B{segment}",
                        start + 40,
                        subject=False,
                        entry=True,
                    ),
                    event(
                        f"S{segment}",
                        start + 100,
                        recovery=0.3,
                        defenders=2,
                    ),
                ]
            )

        result = analyze_match(events, player_names={"P0001": "Ari Aven"})
        window = result.windows[0]
        insight = window.insight
        self.assertTrue(window.persistent_risk)
        self.assertFalse(window.transient_spike)
        self.assertEqual(window.risk_subwindows, 3)
        self.assertIsNotNone(insight)
        self.assertEqual(insight.category, "persistent_defensive_risk")
        source_ids = {item.event_id for item in events}
        self.assertTrue(set(insight.evidence_event_ids).issubset(source_ids))
        self.assertEqual(len(insight.evidence_event_ids), len(set(insight.evidence_event_ids)))
        self.assertEqual(result.player_summaries[0].player_name, "Ari Aven")
        self.assertEqual(result.player_summaries[0].dangerous_turnovers, 3)

    def test_single_concentrated_danger_is_transient_not_persistent(self) -> None:
        events = [
            event(
                "D1",
                100,
                event_type="turnover",
                dangerous=True,
                recovery=0.7,
                defenders=4,
            )
        ]
        events.extend(
            event(f"ENTRY{i}", 110 + i, subject=False, entry=True)
            for i in range(5)
        )
        window = analyze_match(events).windows[0]
        self.assertFalse(window.persistent_risk)
        self.assertTrue(window.transient_spike)
        self.assertEqual(window.risk_subwindows, 1)
        self.assertEqual(window.insight.category, "transient_danger")


if __name__ == "__main__":
    unittest.main()
