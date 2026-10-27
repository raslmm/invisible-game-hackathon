"""Check synthetic dataset IDs, references, and source provenance."""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rows(name: str) -> list[dict[str, str]]:
    with (ROOT / "data" / name).open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def main() -> int:
    matches = rows("matches.csv")
    players = rows("players.csv")
    events = rows("events.csv")
    windows = rows("match_windows.csv")
    labels = rows("ground_truth_labels.csv")
    prompts = rows("evaluation_cases.csv")
    match_ids = {row["match_id"] for row in matches}
    player_ids = {row["player_id"] for row in players}
    event_ids = [row["event_id"] for row in events]
    errors = []
    if len(match_ids) != len(matches):
        errors.append("duplicate match_id")
    if len(player_ids) != len(players):
        errors.append("duplicate player_id")
    if len(set(event_ids)) != len(event_ids):
        errors.append("duplicate event_id")
    if any(row["match_id"] not in match_ids for row in events):
        errors.append("event references unknown match")
    if any(row["player_id"] not in player_ids for row in events):
        errors.append("event references unknown player")
    if any(row["match_id"] not in match_ids for row in windows + labels + prompts):
        errors.append("window, label, or evaluation prompt references unknown match")
    expected_provenance = {
        "matches.csv": (matches, "fully_synthetic"),
        "players.csv": (players, "fully_synthetic"),
        "events.csv": (events, "fully_synthetic"),
        "match_windows.csv": (windows, "fully_synthetic"),
        "ground_truth_labels.csv": (labels, "synthetic_ground_truth"),
        "evaluation_cases.csv": (prompts, "synthetic_evaluation"),
    }
    for filename, (table, expected) in expected_provenance.items():
        if any(row.get("data_origin") != expected for row in table):
            errors.append(f"{filename} provenance is not {expected}")
    teams_by_match = {row["match_id"]: {row["home_team"], row["away_team"]} for row in matches}
    if any(row["team_name"] not in teams_by_match[row["match_id"]] for row in events):
        errors.append("event team does not match its match metadata")
    known_teams = {team for pair in teams_by_match.values() for team in pair}
    if any(row["team_name"] not in known_teams for row in players):
        errors.append("roster team does not match its match metadata")
    subject_by_match = {row["match_id"]: row["subject_team"] for row in matches}

    window_keys = [(row["match_id"], row["window_id"]) for row in windows]
    label_keys = [(row["match_id"], row["window_id"]) for row in labels]
    if len(window_keys) != len(set(window_keys)) or len(label_keys) != len(set(label_keys)):
        errors.append("duplicate match/window key")
    if set(window_keys) != set(label_keys):
        errors.append("match-window features and labels do not reconcile")
    events_by_window: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for event in events:
        try:
            timestamp = int(event["timestamp_seconds"])
            is_subject = event["is_subject_team"] == "1"
            dangerous = event["is_dangerous_turnover"] == "1"
            attacking_entry = event["is_attacking_entry"] == "1"
        except (KeyError, ValueError):
            errors.append("event time or flag has an invalid value")
            continue
        if is_subject != (event["team_name"] == subject_by_match.get(event["match_id"])):
            errors.append(f"subject-team flag conflicts with event {event['event_id']}")
        if dangerous and (not is_subject or event["event_type"] != "turnover"):
            errors.append(f"danger flag conflicts with event {event['event_id']}")
        if attacking_entry and is_subject:
            errors.append(f"attacking-entry flag conflicts with event {event['event_id']}")
        events_by_window[(event["match_id"], timestamp // 900)].append(event)

    for window in windows:
        key = (window["match_id"], int(window["window_start_seconds"]) // 900)
        source = events_by_window.get(key, [])
        dangerous_count = sum(row["is_dangerous_turnover"] == "1" for row in source)
        entry_count = sum(row["is_attacking_entry"] == "1" for row in source)
        turnover_count = sum(
            row["is_subject_team"] == "1" and row["event_type"] == "turnover"
            for row in source
        )
        if dangerous_count != int(window["dangerous_turnovers_observed"]):
            errors.append(f"dangerous-turnover count does not reconcile for {window['window_id']}")
        if entry_count != int(window["opponent_attacking_entries"]):
            errors.append(f"attacking-entry count does not reconcile for {window['window_id']}")
        if turnover_count != int(window["subject_turnovers"]):
            errors.append(f"subject turnover count does not reconcile for {window['window_id']}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(
        f"PASS: {len(matches)} matches, {len(events)} events, {len(players)} players, "
        f"{len(windows)} windows, {len(labels)} labels, {len(prompts)} evaluation prompts; "
        "all references resolve and event, player, and match provenance is synthetic."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
