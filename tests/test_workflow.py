"""Grounding, personalization, and safe-data checks for the narrative workflow."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from invisible_game.workflow import (
    generate_narrative,
    get_match_bundle,
    list_matches,
    provider_status,
)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = get_match_bundle("IGM001")
        cls.insight = cls.bundle["analysis"]["insights"][0]

    def setUp(self) -> None:
        self.model_env = patch.dict(
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
        self.model_env.start()

    def tearDown(self) -> None:
        self.model_env.stop()

    def test_catalog_and_bundle_do_not_expose_ground_truth(self) -> None:
        self.assertEqual(len(list_matches()), 60)
        self.assertNotIn("ground_truth_persistent_risk", self.bundle["match"])
        self.assertNotIn("ground_truth_labels", self.bundle)

    def test_narrative_citations_resolve_to_source_events(self) -> None:
        narrative = generate_narrative("IGM001", self.insight["insight_id"])
        event_ids = {event["event_id"] for event in self.bundle["events"]}
        self.assertTrue(narrative["evidence_event_ids"])
        self.assertTrue(set(narrative["evidence_event_ids"]).issubset(event_ids))
        self.assertEqual(
            {event["event_id"] for event in narrative["evidence_events"]},
            set(narrative["evidence_event_ids"]),
        )
        self.assertEqual(narrative["overlay"]["schema_version"], "match-overlay.v1")
        self.assertEqual(
            narrative["overlay"]["evidence_event_ids"], narrative["evidence_event_ids"]
        )
        self.assertEqual(
            narrative["overlay"]["expires_at_match_seconds"]
            - narrative["overlay"]["valid_from_match_seconds"],
            900,
        )
        self.assertEqual(
            [stage["agent"] for stage in narrative["trace"]["stages"]],
            ["Tactical Analyst", "Fan Storyteller"],
        )

    def test_live_narrative_contains_no_events_after_its_closed_window(self) -> None:
        narrative = generate_narrative("IGM001", self.insight["insight_id"])
        window_end = self.insight["signals"]["window_end_seconds"]
        self.assertTrue(
            all(event["timestamp_seconds"] < window_end for event in narrative["evidence_events"])
        )

    def test_audience_modes_change_story_but_keep_facts_and_evidence(self) -> None:
        results = [
            generate_narrative("IGM001", self.insight["insight_id"], persona=persona)
            for persona in ("analyst", "casual", "club", "player")
        ]
        self.assertEqual(len({result["presentation"]["story"] for result in results}), 4)
        self.assertTrue(all(result["facts"] == results[0]["facts"] for result in results))
        self.assertTrue(
            all(result["evidence_event_ids"] == results[0]["evidence_event_ids"] for result in results)
        )

    def test_favourite_opposition_and_spanish_story_are_personalized(self) -> None:
        match = self.bundle["match"]
        narrative = generate_narrative(
            "IGM001",
            self.insight["insight_id"],
            persona="club",
            language="es",
            favorite_team=match["opponent_team"],
        )
        self.assertEqual(narrative["language"], "es")
        self.assertIn(match["opponent_team"], narrative["presentation"]["story"])
        self.assertIn("entradas rivales", narrative["presentation"]["story"])

    def test_player_mode_names_the_selected_player(self) -> None:
        player = self.bundle["players"][0]
        narrative = generate_narrative(
            "IGM001",
            self.insight["insight_id"],
            persona="player",
            focus_player_id=player["player_id"],
        )
        self.assertIn(player["player_name"], narrative["presentation"]["story"])

    def test_model_is_optional_and_offline_mode_is_explicit(self) -> None:
        status = provider_status()
        if not status["model_ready"]:
            self.assertEqual(status["provider"], "local")
            self.assertIn("Offline", status["message"])

    def test_unknown_insight_and_persona_are_rejected(self) -> None:
        with self.assertRaises(KeyError):
            generate_narrative("IGM001", "not-an-insight")
        with self.assertRaises(ValueError):
            generate_narrative("IGM001", self.insight["insight_id"], persona="invented")


if __name__ == "__main__":
    unittest.main()
