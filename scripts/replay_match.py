"""Replay one synthetic match and emit versioned JSONL event envelopes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from invisible_game import EventEnvelope, EventReplay, load_match_events  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay synthetic match events as a versioned JSONL stream."
    )
    parser.add_argument(
        "--events",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "events.csv",
        help="Path to the synthetic events CSV (default: data/events.csv).",
    )
    parser.add_argument(
        "--match-id",
        help="Match to replay (defaults to the first match in the CSV).",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=60.0,
        help="Playback speed as a multiple of match time (default: 60x).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum events to emit; use 0 to replay the full match (default: 20).",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Emit immediately without simulating the gaps between source timestamps.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Step through events and use p (pause), r (reset), s SPEED, or q (quit).",
    )
    return parser


def _write_envelope(envelope: EventEnvelope) -> None:
    payload = envelope.to_dict()
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _run_interactive(replay: EventReplay, limit: int) -> int:
    emitted_this_run = 0
    print(
        "Enter/n: next event | p: pause or resume | r: reset | s SPEED: change speed | q: quit",
        file=sys.stderr,
    )
    while True:
        if limit and emitted_this_run >= limit:
            print(f"Event limit reached ({limit}); resetting starts a new replay.", file=sys.stderr)
        print("Replay command: ", end="", file=sys.stderr, flush=True)
        command = input().strip()
        if command.lower() in {"q", "quit"}:
            return emitted_this_run
        if command.lower() in {"p", "pause"}:
            paused = replay.toggle_pause()
            print("Paused." if paused else "Resumed.", file=sys.stderr)
            continue
        if command.lower() in {"r", "reset"}:
            replay.reset()
            emitted_this_run = 0
            print("Replay reset.", file=sys.stderr)
            continue
        if command.lower().startswith("s "):
            try:
                replay.set_speed(float(command.split(maxsplit=1)[1]))
            except (IndexError, ValueError) as exc:
                print(f"Invalid speed: {exc}", file=sys.stderr)
                continue
            print(f"Speed set to {replay.speed:g}x.", file=sys.stderr)
            continue
        if command.lower() not in {"", "n", "next"}:
            print("Unknown command.", file=sys.stderr)
            continue
        if limit and emitted_this_run >= limit:
            continue
        envelope = replay.next_envelope()
        if envelope is None:
            if replay.paused:
                print("Replay is paused; enter p to resume.", file=sys.stderr)
            else:
                print("Match replay complete.", file=sys.stderr)
                return emitted_this_run
            continue
        _write_envelope(envelope)
        emitted_this_run += 1


def main() -> int:
    args = _parser().parse_args()
    if args.limit < 0:
        print("--limit must be 0 or a positive integer.", file=sys.stderr)
        return 2

    try:
        events = load_match_events(args.events, args.match_id)
        replay = EventReplay(
            events,
            speed=args.speed,
            realtime=not args.no_wait,
        )
        selected_match = events[0].match_id
        print(
            f"Replaying {selected_match}: {len(events)} source rows at {replay.speed:g}x.",
            file=sys.stderr,
        )

        if args.interactive:
            emitted = _run_interactive(replay, args.limit)
        else:
            emitted = 0
            while not args.limit or emitted < args.limit:
                envelope = replay.next_envelope()
                if envelope is None:
                    break
                _write_envelope(envelope)
                emitted += 1
        print(
            f"Emitted {emitted} events; suppressed {replay.duplicates_skipped} duplicate event IDs.",
            file=sys.stderr,
        )
    except (OSError, ValueError) as exc:
        print(f"Replay failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
