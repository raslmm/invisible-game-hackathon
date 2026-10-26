"""Analyze a synthetic match and print metrics and evidence as JSON."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from invisible_game import analyze_match, load_match_events  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute deterministic match windows, player summaries, and insights."
    )
    parser.add_argument(
        "--events",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "events.csv",
        help="Path to the synthetic events CSV (default: data/events.csv).",
    )
    parser.add_argument(
        "--players",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "players.csv",
        help="Path to the synthetic roster CSV (default: data/players.csv).",
    )
    parser.add_argument(
        "--match-id",
        help="Match to analyze (defaults to the first match in the events CSV).",
    )
    return parser


def _load_player_names(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not {"player_id", "player_name"}.issubset(reader.fieldnames):
            raise ValueError(f"Roster CSV must contain player_id and player_name: {path}")
        return {
            row["player_id"]: row["player_name"]
            for row in reader
            if row.get("player_id") and row.get("player_name")
        }


def main() -> int:
    args = _parser().parse_args()
    try:
        events = load_match_events(args.events, args.match_id)
        analysis = analyze_match(
            events,
            player_names=_load_player_names(args.players),
        )
        print(json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
