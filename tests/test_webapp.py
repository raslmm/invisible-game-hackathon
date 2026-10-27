"""HTTP contract checks for the local demo app."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from invisible_game.webapp import MatchHandler


class WebAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model_env = patch.dict(
            os.environ,
            {
                key: ""
                for key in (
                    "AZURE_AI_FOUNDRY_ENDPOINT",
                    "AZURE_AI_MODEL_DEPLOYMENT",
                    "AZURE_INFERENCE_CREDENTIAL",
                    "AZURE_OPENAI_ENDPOINT",
                    "AZURE_OPENAI_DEPLOYMENT",
                    "AZURE_OPENAI_API_KEY",
                )
            },
            clear=False,
        )
        cls.model_env.start()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MatchHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.model_env.stop()

    def get_json(self, path: str) -> dict[str, object]:
        with urlopen(self.base + path, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_static_app_and_health_routes(self) -> None:
        with urlopen(self.base + "/", timeout=5) as response:
            self.assertIn(b"THE INVISIBLE GAME", response.read())
        self.assertEqual(self.get_json("/api/health")["status"], "ok")

    def test_full_bundle_route_is_not_exposed_during_replay(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/api/matches/IGM001/bundle", timeout=5)
        self.assertEqual(caught.exception.code, 404)

    def test_metadata_hides_future_events_and_synthetic_labels(self) -> None:
        metadata = self.get_json("/api/matches/IGM001/metadata")
        self.assertEqual(metadata["match"]["match_id"], "IGM001")
        self.assertNotIn("events", metadata)
        self.assertNotIn("analysis", metadata)
        self.assertNotIn("ground_truth_persistent_risk", metadata["match"])

    def test_replay_stream_emits_one_typed_event_and_provisional_window(self) -> None:
        with urlopen(self.base + "/api/matches/IGM001/stream?from=0&speed=1200", timeout=5) as response:
            self.assertIn("text/event-stream", response.headers["Content-Type"])
            frame = response.readline().decode("utf-8").strip()
        payload = json.loads(frame.removeprefix("data: "))
        self.assertEqual(payload["message_type"], "replay_update")
        self.assertEqual(payload["sequence"], 1)
        self.assertEqual(payload["event"]["event_id"], "EV000001")
        self.assertEqual(payload["completed_windows"], [])
        self.assertTrue(payload["live_window"]["provisional"])
        self.assertNotIn("insight", payload["live_window"])
        self.assertGreaterEqual(payload["metrics_processing_ms"], 0)

    def test_full_replay_emits_all_events_then_closes_all_windows(self) -> None:
        seen_events = 0
        windows: dict[int, dict[str, object]] = {}
        complete = None
        started = time.monotonic()
        with urlopen(self.base + "/api/matches/IGM001/stream?from=0&speed=1200", timeout=20) as response:
            while time.monotonic() - started < 20:
                line = response.readline()
                if not line:
                    break
                if not line.startswith(b"data: "):
                    continue
                payload = json.loads(line[6:].decode("utf-8"))
                for window in payload.get("completed_windows", []):
                    windows[window["window_start_seconds"]] = window
                if payload.get("message_type") == "replay_update":
                    seen_events += 1
                if payload.get("message_type") == "match_complete":
                    complete = payload
                    break
        self.assertEqual(seen_events, 288)
        self.assertIsNotNone(complete)
        self.assertEqual(complete["events_emitted"], 288)
        self.assertEqual(len(windows), 6)
        self.assertTrue(any(window["persistent_risk"] for window in windows.values()))

    def test_narrative_and_recap_are_machine_readable(self) -> None:
        narrative = self.post_json(
            "/api/narrative",
            {
                "match_id": "IGM001",
                "insight_id": "IGM001-W2-transient_danger",
                "persona": "casual",
            },
        )
        self.assertTrue(narrative["evidence_event_ids"])
        recap = self.post_json("/api/recap", {"match_id": "IGM001"})
        self.assertEqual(recap["schema_version"], "invisible-game.recap.v1")
        self.assertTrue(recap["chapters"])
        self.assertTrue(
            all(chapter["overlay"]["schema_version"] == "match-overlay.v1" for chapter in recap["chapters"])
        )

    def test_unknown_match_returns_not_found(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/api/matches/UNKNOWN/bundle", timeout=5)
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
