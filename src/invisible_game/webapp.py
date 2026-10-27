"""Dependency-free local web server for The Invisible Game demo."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qs, unquote, urlparse

from . import EventEnvelope, EventReplay, analyze_match, load_match_events

from .workflow import (
    generate_narrative,
    generate_recap,
    get_match_bundle,
    list_matches,
    provider_status,
    recent_traces,
    get_match_metadata,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPOSITORY_ROOT / "web"
MAX_BODY_BYTES = 8192


class MatchHandler(BaseHTTPRequestHandler):
    server_version = "InvisibleGame/1.0"

    def _write(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._write(status, body, "application/json; charset=utf-8")

    def _static(self, name: str, content_type: str) -> None:
        path = (WEB_DIR / name).resolve()
        if WEB_DIR.resolve() not in path.parents or not path.is_file():
            self._json(404, {"error": "Page asset not found"})
            return
        self._write(200, path.read_bytes(), content_type)

    def _read_body(self) -> dict[str, object]:
        length_text = self.headers.get("Content-Length", "0")
        try:
            length = int(length_text)
        except ValueError as exc:
            raise ValueError("Invalid request body length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("Request body is too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def _sse(self, value: dict[str, object]) -> None:
        frame = "data: " + json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n\n"
        self.wfile.write(frame.encode("utf-8"))
        self.wfile.flush()

    def _replay_stream(self, match_id: str, start_index: int, speed: float) -> None:
        metadata = get_match_metadata(match_id)
        source_events = load_match_events(
            Path(__file__).resolve().parents[2] / "data" / "events.csv",
            match_id,
        )
        if start_index < 0 or start_index > len(source_events):
            raise ValueError("Replay cursor is outside the match event range")
        if not 1 <= speed <= 1200:
            raise ValueError("Replay speed must be between 1x and 1200x")

        prefix = list(source_events[:start_index])
        subject_team = metadata["match"]["subject_team"]
        player_names = {row["player_id"]: row["player_name"] for row in metadata["players"]}
        sent_window_ends: set[int] = set()
        if prefix:
            last_prefix = prefix[-1].timestamp_seconds
            sent_window_ends = set(range(900, (last_prefix // 900) * 900 + 1, 900))

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.close_connection = True

        seen = list(prefix)
        try:
            replay = (
                EventReplay(source_events[start_index:], speed=speed, realtime=True)
                if start_index < len(source_events)
                else None
            )
            sequence = start_index
            while replay is not None and (envelope := replay.next_envelope()) is not None:
                event = envelope.event
                seen.append(event)
                sequence += 1
                analysis_end = ((event.timestamp_seconds // 900) + 1) * 900
                analysis_started = perf_counter()
                analysis = analyze_match(
                    seen,
                    subject_team=subject_team,
                    player_names=player_names,
                    match_end_seconds=max(900, analysis_end),
                )
                metrics_elapsed_ms = round((perf_counter() - analysis_started) * 1000, 2)
                completed = [
                    window.to_dict()
                    for window in analysis.windows
                    if window.window_end_seconds <= event.timestamp_seconds
                    and window.window_end_seconds not in sent_window_ends
                ]
                sent_window_ends.update(window["window_end_seconds"] for window in completed)
                current = analysis.windows[-1]
                live_window = {
                    "window_start_seconds": current.window_start_seconds,
                    "window_end_seconds": current.window_end_seconds,
                    "event_count": current.event_count,
                    "subject_event_share": current.subject_event_share,
                    "subject_turnovers": current.subject_turnovers,
                    "dangerous_turnovers": current.dangerous_turnovers,
                    "opponent_attacking_entries": current.opponent_attacking_entries,
                    "average_event_pressure": current.average_event_pressure,
                    "average_subject_recovery_speed": current.average_subject_recovery_speed,
                    "average_subject_defenders_behind_ball": current.average_subject_defenders_behind_ball,
                    "average_subject_fatigue": current.average_subject_fatigue,
                    "event_rate_per_minute": current.event_rate_per_minute,
                    "risk_score": current.risk_score,
                    "provisional": True,
                }
                message = EventEnvelope(sequence=sequence, event=event).to_dict()
                message.update(
                    {
                        "message_type": "replay_update",
                        "event_index": sequence - 1,
                        "completed_windows": completed,
                        "live_window": live_window,
                        "metrics_processing_ms": metrics_elapsed_ms,
                    }
                )
                self._sse(message)

            if seen:
                final_timestamp = seen[-1].timestamp_seconds
                match_end = ((final_timestamp // 900) + 1) * 900
                final_analysis = analyze_match(
                    seen,
                    subject_team=subject_team,
                    player_names=player_names,
                    match_end_seconds=max(900, match_end),
                )
                final_windows = [
                    window.to_dict()
                    for window in final_analysis.windows
                    if window.window_end_seconds not in sent_window_ends
                ]
                self._sse(
                    {
                        "schema_version": "invisible-game.stream-control.v1",
                        "message_type": "match_complete",
                        "match_id": match_id,
                        "events_emitted": len(seen),
                        "duplicate_event_ids_skipped": replay.duplicates_skipped if replay else 0,
                        "completed_windows": final_windows,
                        "player_summaries": [player.to_dict() for player in final_analysis.player_summaries],
                    }
                )
            else:
                self._sse(
                    {
                        "schema_version": "invisible-game.stream-control.v1",
                        "message_type": "match_complete",
                        "match_id": match_id,
                        "events_emitted": 0,
                        "completed_windows": [],
                    }
                )
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        try:
            if route == "/":
                self._static("index.html", "text/html; charset=utf-8")
            elif route == "/app.js":
                self._static("app.js", "text/javascript; charset=utf-8")
            elif route == "/styles.css":
                self._static("styles.css", "text/css; charset=utf-8")
            elif route == "/api/health":
                self._json(
                    200,
                    {
                        "status": "ok",
                        "project": "The Invisible Game",
                        "provider": provider_status(),
                    },
                )
            elif route == "/api/matches":
                self._json(200, {"matches": list_matches()})
            elif route == "/api/traces":
                self._json(200, {"traces": recent_traces()})
            elif route.startswith("/api/matches/") and route.endswith("/metadata"):
                match_id = unquote(route[len("/api/matches/") : -len("/metadata")].strip("/"))
                self._json(200, get_match_metadata(match_id))
            elif route.startswith("/api/matches/") and route.endswith("/stream"):
                match_id = unquote(route[len("/api/matches/") : -len("/stream")].strip("/"))
                query = parse_qs(urlparse(self.path).query)
                try:
                    start_index = int(query.get("from", ["0"])[0])
                    speed = float(query.get("speed", ["120"])[0])
                except ValueError as exc:
                    raise ValueError("Replay cursor and speed must be numeric") from exc
                self._replay_stream(match_id, start_index, speed)
            elif route.startswith("/api/export/"):
                match_id = unquote(route[len("/api/export/") :].strip("/"))
                payload = {
                    "schema_version": "invisible-game.export.v1",
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "bundle": get_match_bundle(match_id),
                }
                body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{match_id}-invisible-game.json"',
                )
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json(404, {"error": "Route not found"})
        except KeyError as exc:
            self._json(404, {"error": str(exc).strip("'")})
        except (OSError, ValueError) as exc:
            self._json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            body = self._read_body()
            match_id = str(body.get("match_id", ""))
            if route == "/api/narrative":
                response = generate_narrative(
                    match_id,
                    str(body.get("insight_id", "")),
                    persona=str(body.get("persona", "analyst")),
                    language=str(body.get("language", "en")),
                    favorite_team=(
                        str(body["favorite_team"])
                        if body.get("favorite_team")
                        else None
                    ),
                    focus_player_id=(
                        str(body["focus_player_id"])
                        if body.get("focus_player_id")
                        else None
                    ),
                )
                self._json(200, response)
            elif route == "/api/recap":
                response = generate_recap(
                    match_id,
                    persona=str(body.get("persona", "casual")),
                    language=str(body.get("language", "en")),
                    favorite_team=(
                        str(body["favorite_team"])
                        if body.get("favorite_team")
                        else None
                    ),
                    focus_player_id=(
                        str(body["focus_player_id"])
                        if body.get("focus_player_id")
                        else None
                    ),
                )
                self._json(200, response)
            else:
                self._json(404, {"error": "Route not found"})
        except KeyError as exc:
            self._json(404, {"error": str(exc).strip("'")})
        except (OSError, ValueError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "Workflow failed; check the local server log."})

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stdout.write(f"{self.log_date_time_string()} {self.address_string()} {fmt % args}\n")


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), MatchHandler)
    server.daemon_threads = True
    print(f"The Invisible Game is ready at http://{host}:{port}", flush=True)
    print("Synthetic dataset only. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping local server.", flush=True)
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Invisible Game match viewer.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8765, help="Port (default 8765).")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
