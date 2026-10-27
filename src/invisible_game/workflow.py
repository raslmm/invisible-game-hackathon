"""Evidence-first Analyst -> Fan Storyteller workflow and match data service.

The deterministic path is complete and offline-safe. When a compatible Microsoft
Foundry Models OpenAI-v1 endpoint is configured, two bounded model calls can
select evidence and adapt its presentation. Facts and cited event IDs remain
owned by the deterministic metrics engine.
"""
from __future__ import annotations

import csv
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import analyze_match, load_match_events

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPOSITORY_ROOT / "data"
SUPPORTED_PERSONAS = {"analyst", "casual", "club", "player"}
SUPPORTED_LANGUAGES = {"en", "es"}
PUBLIC_MATCH_FIELDS = (
    "match_id",
    "home_team",
    "away_team",
    "competition",
    "match_date",
    "scenario_type",
    "scenario_title",
    "subject_team",
    "opponent_team",
    "scenario_description",
    "data_origin",
)
_TRACE_LOCK = threading.Lock()
_TRACE_LOG: list[dict[str, Any]] = []


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def _load_local_config() -> None:
    """Read only the documented model keys from an ignored local .env file."""
    path = REPOSITORY_ROOT / ".env"
    if not path.is_file():
        return
    allowed = {
        "AZURE_AI_FOUNDRY_ENDPOINT",
        "AZURE_AI_MODEL_DEPLOYMENT",
        "AZURE_INFERENCE_CREDENTIAL",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_API_KEY",
    }
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key in allowed and value:
            os.environ.setdefault(key, value)


@lru_cache(maxsize=1)
def _catalog_rows() -> tuple[dict[str, str], ...]:
    return tuple(_read_csv(DATA_DIR / "matches.csv"))


@lru_cache(maxsize=1)
def _player_rows() -> tuple[dict[str, str], ...]:
    return tuple(_read_csv(DATA_DIR / "players.csv"))


def list_matches() -> list[dict[str, str]]:
    """Expose safe match metadata, never the synthetic ground-truth labels."""
    return [
        {
            key: row[key]
            for key in PUBLIC_MATCH_FIELDS
        }
        for row in _catalog_rows()
    ]


def _find_match(match_id: str) -> dict[str, str]:
    match = next((row for row in _catalog_rows() if row["match_id"] == match_id), None)
    if match is None:
        raise KeyError(f"Unknown match_id: {match_id}")
    return {key: match[key] for key in PUBLIC_MATCH_FIELDS}


@lru_cache(maxsize=12)
def _source_events(match_id: str) -> tuple[Any, ...]:
    _find_match(match_id)
    return tuple(load_match_events(DATA_DIR / "events.csv", match_id))


def get_match_metadata(match_id: str) -> dict[str, Any]:
    """Return match and roster metadata without preloading future events or alerts."""
    match = _find_match(match_id)
    roster = [
        row
        for row in _player_rows()
        if row["team_name"] in {match["home_team"], match["away_team"]}
    ]
    return {"schema_version": "invisible-game.match-metadata.v1", "match": match, "players": roster}


@lru_cache(maxsize=12)
def get_match_bundle(match_id: str) -> dict[str, Any]:
    """Load a match once and return its source events and deterministic analysis."""
    match = _find_match(match_id)
    events = _source_events(match_id)
    roster = [row for row in _player_rows() if row["team_name"] in {match["home_team"], match["away_team"]}]
    names = {row["player_id"]: row["player_name"] for row in roster}
    analysis = analyze_match(events, player_names=names).to_dict()
    return {
        "schema_version": "invisible-game.match-bundle.v1",
        "match": match,
        "events": [event.to_dict() for event in events],
        "players": roster,
        "analysis": analysis,
    }


def _closed_insight_bundle(match_id: str, insight_id: str) -> dict[str, Any]:
    """Rebuild only through the cited insight's closed window, never later events."""
    match = _find_match(match_id)
    source_events = _source_events(match_id)
    roster = [
        row
        for row in _player_rows()
        if row["team_name"] in {match["home_team"], match["away_team"]}
    ]
    names = {row["player_id"]: row["player_name"] for row in roster}
    max_window = source_events[-1].timestamp_seconds // 900 + 1
    for number in range(1, max_window + 1):
        window_end = number * 900
        prefix = [event for event in source_events if event.timestamp_seconds < window_end]
        if not prefix:
            continue
        analysis = analyze_match(
            prefix,
            subject_team=match["subject_team"],
            player_names=names,
            match_end_seconds=window_end,
        )
        if any(item.insight_id == insight_id for item in analysis.insights):
            return {
                "schema_version": "invisible-game.match-prefix.v1",
                "match": match,
                "events": [event.to_dict() for event in prefix],
                "players": roster,
                "analysis": analysis.to_dict(),
            }
    raise KeyError(f"Unknown closed-window insight for match {match_id}: {insight_id}")


def provider_status() -> dict[str, Any]:
    _load_local_config()
    endpoint = (
        os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT")
        or os.environ.get("AZURE_OPENAI_ENDPOINT")
        or ""
    ).strip()
    deployment = (
        os.environ.get("AZURE_AI_MODEL_DEPLOYMENT")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        or ""
    ).strip()
    credential = (
        os.environ.get("AZURE_INFERENCE_CREDENTIAL")
        or os.environ.get("AZURE_OPENAI_API_KEY")
        or ""
    ).strip()
    parsed_endpoint = urlsplit(endpoint)
    configured = bool(parsed_endpoint.scheme == "https" and parsed_endpoint.netloc and deployment and credential)
    return {
        "provider": "azure_ai_foundry" if configured else "local",
        "model_ready": configured,
        "model_deployment": deployment if configured else None,
        "message": (
            "Azure AI Foundry model workflow ready"
            if configured
            else "Offline evidence-first workflow active"
        ),
    }


def _call_foundry(system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
    """Call the documented Foundry Models OpenAI-v1 chat-completions route."""
    status = provider_status()
    if not status["model_ready"]:
        raise RuntimeError("Azure model endpoint is not configured")
    endpoint = (
        os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT")
        or os.environ.get("AZURE_OPENAI_ENDPOINT")
        or ""
    ).strip().rstrip("/")
    if urlsplit(endpoint).scheme != "https":
        raise ValueError("The model endpoint must use HTTPS")
    deployment = (
        os.environ.get("AZURE_AI_MODEL_DEPLOYMENT")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        or ""
    ).strip()
    credential = (
        os.environ.get("AZURE_INFERENCE_CREDENTIAL")
        or os.environ.get("AZURE_OPENAI_API_KEY")
        or ""
    ).strip()
    if endpoint.endswith("/openai/v1"):
        base_url = endpoint
    else:
        base_url = endpoint + "/openai/v1"
    url = base_url + "/chat/completions"
    request_body = {
        "model": deployment,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
            },
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "api-key": credential,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError("Model response must be a JSON object")
    return result


def _record_trace(trace: dict[str, Any]) -> None:
    safe_trace = {
        "request_id": trace["request_id"],
        "match_id": trace["match_id"],
        "insight_id": trace.get("insight_id"),
        "provider": trace["provider"],
        "stages": trace["stages"],
        "editorial_guard": trace.get("editorial_guard"),
        "overall_ms": trace["overall_ms"],
    }
    with _TRACE_LOCK:
        _TRACE_LOG.append(safe_trace)
        del _TRACE_LOG[:-100]
    print(json.dumps({"workflow_trace": safe_trace}, separators=(",", ":")), flush=True)


def recent_traces() -> list[dict[str, Any]]:
    with _TRACE_LOCK:
        return list(reversed(_TRACE_LOG))


def _minute(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _make_context(
    bundle: dict[str, Any],
    insight: dict[str, Any],
    *,
    persona: str,
    language: str,
    favorite_team: str | None,
    focus_player_id: str | None,
) -> dict[str, Any]:
    event_by_id = {event["event_id"]: event for event in bundle["events"]}
    player_by_id = {player["player_id"]: player for player in bundle["players"]}
    evidence = [
        event_by_id[event_id]
        for event_id in insight["evidence_event_ids"]
        if event_id in event_by_id
    ]
    if not evidence:
        raise ValueError("No source events exist for this insight")
    names = [player_by_id[e["player_id"]]["player_name"] for e in evidence if e["player_id"] in player_by_id]
    focus_player = player_by_id.get(focus_player_id or "")
    focus_count = sum(event["player_id"] == focus_player_id for event in evidence)
    signals = insight["signals"]
    team = bundle["match"]["subject_team"]
    opponent = bundle["match"]["opponent_team"]
    return {
        "match": bundle["match"],
        "insight": insight,
        "window_label": f"{_minute(signals['window_start_seconds'])}–{_minute(signals['window_end_seconds'])}",
        "evidence_event_ids": [event["event_id"] for event in evidence],
        "evidence_events": [
            {
                "event_id": event["event_id"],
                "time": _minute(event["timestamp_seconds"]),
                "team": event["team_name"],
                "player": player_by_id.get(event["player_id"], {}).get("player_name", event["player_id"]),
                "event_type": event["event_type"],
                "outcome": event["outcome"],
                "pitch_zone": event["pitch_zone"],
                "pitch_lane": event["pitch_lane"],
                "pressure_intensity": event["pressure_intensity"],
            }
            for event in evidence
        ],
        "evidence_player_names": names,
        "signals": signals,
        "facts": {
            "subject_team": team,
            "opponent_team": opponent,
            "favorite_team": favorite_team if favorite_team in {team, opponent} else team,
            "focus_player": focus_player["player_name"] if focus_player else None,
            "focus_player_evidence_events": focus_count,
            "category": insight["category"],
            "window_label": f"{_minute(signals['window_start_seconds'])}–{_minute(signals['window_end_seconds'])}",
            "dangerous_turnovers": signals["dangerous_turnovers"],
            "opponent_attacking_entries": signals["opponent_attacking_entries"],
            "risk_subwindows": signals["risk_subwindows"],
            "risk_score": signals["risk_score"],
            "average_recovery_speed": signals["average_subject_recovery_speed"],
            "average_defensive_cover": signals["average_subject_defenders_behind_ball"],
        },
        "persona": persona,
        "language": language,
        "display_mode": "opposition_club" if favorite_team == opponent else persona,
    }


def _local_headline(context: dict[str, Any]) -> str:
    category = context["facts"]["category"]
    language = context["language"]
    if language == "es":
        return (
            "Exposición defensiva repetida"
            if category == "persistent_defensive_risk"
            else "Momento peligroso, aún no es un patrón"
        )
    return (
        "Repeated defensive exposure"
        if category == "persistent_defensive_risk"
        else "A dangerous moment, not yet a pattern"
    )


def _local_story(context: dict[str, Any]) -> dict[str, str]:
    facts = context["facts"]
    persona = context["persona"]
    favorite = facts["favorite_team"]
    subject = facts["subject_team"]
    focus = facts["focus_player"]
    danger = facts["dangerous_turnovers"]
    entries = facts["opponent_attacking_entries"]
    repeated = facts["risk_subwindows"]
    recovery = facts["average_recovery_speed"]
    cover = facts["average_defensive_cover"]
    persistent = facts["category"] == "persistent_defensive_risk"

    if context["language"] == "es":
        headline = _local_headline(context)
        if persona == "player":
            if focus and facts["focus_player_evidence_events"]:
                story = (
                    f"Enfoque en {focus}: aparece en {facts['focus_player_evidence_events']} "
                    f"evento(s) citado(s). El equipo registró {danger} pérdidas peligrosas y "
                    f"{entries} entradas rivales; la señal se repitió en {repeated} de 3 tramos."
                )
            elif focus:
                story = (
                    f"Enfoque en {focus}: no aparece en los eventos citados de esta alerta. "
                    f"El patrón del equipo se mantiene: {danger} pérdidas peligrosas, "
                    f"{entries} entradas rivales y {repeated} de 3 tramos con señal."
                )
            else:
                story = f"El equipo registró {danger} pérdidas peligrosas y {entries} entradas rivales en este tramo."
        elif persona == "club":
            if favorite == subject:
                story = (
                    f"Para {favorite}, este tramo dejó {danger} pérdidas peligrosas y "
                    f"{entries} entradas rivales. La señal apareció en {repeated} de 3 tramos."
                )
            else:
                story = (
                    f"Para {favorite}, este tramo muestra al rival {subject} bajo presión: "
                    f"{danger} pérdidas peligrosas, {entries} entradas rivales y una señal "
                    f"repetida en {repeated} de 3 tramos."
                )
        elif persona == "casual":
            status = "se repitió" if persistent else "se concentró en un solo tramo"
            story = (
                f"El peligro {status}: el tramo incluyó {danger} pérdidas peligrosas y "
                f"{entries} llegadas rivales durante {repeated} de 3 tramos de cinco minutos."
            )
        else:
            story = (
                f"Entre {facts['window_label']}, {subject} registró {danger} pérdidas peligrosas "
                f"y {entries} entradas rivales. La señal apareció en {repeated} de 3 tramos; "
                f"recuperación media {recovery:.2f} y cobertura media {cover:.1f} defensores."
            )
        why = (
            "La recurrencia separa una exposición estructural de un episodio aislado."
            if persistent
            else "Un episodio peligroso merece atención, pero por sí solo no demuestra un patrón sostenido."
        )
        return {"headline": headline, "story": story, "why_now": why}

    headline = _local_headline(context)
    if persona == "player":
        if focus and facts["focus_player_evidence_events"]:
            story = (
                f"Player focus — {focus} appears in "
                f"{facts['focus_player_evidence_events']} cited event(s). The team recorded "
                f"{danger} dangerous turnovers and {entries} opponent entries; the signal "
                f"recurred in {repeated} of 3 five-minute segments."
            )
        elif focus:
            story = (
                f"Player focus — {focus} does not appear in this alert's cited events. "
                f"The team pattern remains: {danger} dangerous turnovers, {entries} "
                f"opponent entries, and a signal in {repeated} of 3 segments."
            )
        else:
            story = f"The team recorded {danger} dangerous turnovers and {entries} opponent entries in this spell."
    elif persona == "club":
        if favorite == subject:
            story = (
                f"For {favorite}, this spell brought {danger} dangerous turnovers and "
                f"{entries} opponent entries. The signal appeared in {repeated} of 3 segments."
            )
        else:
            story = (
                f"For {favorite}, this spell shows {subject} under pressure: {danger} "
                f"dangerous turnovers, {entries} opponent entries, with a repeated signal "
                f"across {repeated} of 3 segments."
            )
    elif persona == "casual":
        pattern = "kept returning" if persistent else "was concentrated in one short spell"
        story = (
            f"The danger {pattern}: the spell included {danger} risky turnovers and "
            f"{entries} opponent entries across {repeated} of the three five-minute spells."
        )
    else:
        story = (
            f"From {facts['window_label']}, {subject} recorded {danger} dangerous turnovers "
            f"and {entries} opponent attacking entries. The signal recurred in {repeated} "
            f"of 3 segments; mean recovery index was {recovery:.2f}, with "
            f"{cover:.1f} defenders behind the ball on average."
        )
    why = (
        "Recurrence across separate five-minute segments supports a sustained exposure pattern."
        if persistent
        else "A concentrated spell merits attention, but one segment alone does not establish a sustained pattern."
    )
    return {"headline": headline, "story": story, "why_now": why}


def _validate_analyst(result: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    expected_category = context["facts"]["category"]
    citations = result.get("evidence_event_ids")
    if result.get("claim_type") != expected_category:
        raise ValueError("Analyst category differs from the deterministic signal")
    if not isinstance(citations, list) or not citations:
        raise ValueError("Analyst did not return event citations")
    allowed = set(context["evidence_event_ids"])
    if any(not isinstance(event_id, str) or event_id not in allowed for event_id in citations):
        raise ValueError("Analyst cited an event outside the verified evidence set")
    return {
        "claim_type": expected_category,
        "evidence_event_ids": list(dict.fromkeys(citations)),
    }


def _validate_story(result: dict[str, Any], context: dict[str, Any], analyst: dict[str, Any]) -> dict[str, str]:
    allowed = set(analyst["evidence_event_ids"])
    citations = result.get("evidence_event_ids")
    if not isinstance(citations, list) or not citations:
        raise ValueError("Storyteller did not return event citations")
    if any(not isinstance(event_id, str) or event_id not in allowed for event_id in citations):
        raise ValueError("Storyteller cited an unverified event")
    headline = result.get("headline")
    story = result.get("story")
    why_now = result.get("why_now")
    if not all(isinstance(value, str) and value.strip() for value in (headline, story, why_now)):
        raise ValueError("Storyteller response is missing required text")
    if any(len(value) > 260 for value in (headline, story, why_now)):
        raise ValueError("Storyteller response exceeds its length limit")
    valid_numbers = {
        str(context["facts"][key])
        for key in (
            "dangerous_turnovers",
            "opponent_attacking_entries",
            "risk_subwindows",
        )
    }
    valid_numbers.update(
        f"{float(context['facts'][key]):.2f}"
        for key in ("average_recovery_speed",)
    )
    valid_numbers.update(
        {f"{float(context['facts']['average_defensive_cover']):.1f}"}
    )
    for value in (headline, story, why_now):
        for number in re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", value):
            if number not in valid_numbers:
                raise ValueError("Storyteller introduced a numeric claim not in the evidence card")
        if re.search(
            r"\b(caused|causes|because of|as a result|led to a goal|will score|will win)\b"
            r"|\b(causó|causa|debido a|como resultado|marcará|ganará|llegará el gol)\b",
            value,
            flags=re.IGNORECASE,
        ):
            raise ValueError("Storyteller introduced a causal or predictive claim")
    return {
        "headline": headline.strip(),
        "story": story.strip(),
        "why_now": why_now.strip(),
    }


def generate_narrative(
    match_id: str,
    insight_id: str,
    *,
    persona: str = "analyst",
    language: str = "en",
    favorite_team: str | None = None,
    focus_player_id: str | None = None,
) -> dict[str, Any]:
    if persona not in SUPPORTED_PERSONAS:
        raise ValueError(f"Unsupported persona: {persona}")
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    started = time.perf_counter()
    request_id = str(uuid.uuid4())
    bundle = _closed_insight_bundle(match_id, insight_id)
    insight = next(
        (item for item in bundle["analysis"]["insights"] if item["insight_id"] == insight_id),
        None,
    )
    if insight is None:
        raise KeyError(f"Unknown insight_id for match {match_id}: {insight_id}")
    context = _make_context(
        bundle,
        insight,
        persona=persona,
        language=language,
        favorite_team=favorite_team,
        focus_player_id=focus_player_id,
    )
    provider = provider_status()
    trace: dict[str, Any] = {
        "request_id": request_id,
        "match_id": match_id,
        "insight_id": insight_id,
        "provider": provider["provider"],
        "stages": [],
    }

    analyst_started = time.perf_counter()
    try:
        if provider["model_ready"]:
            analyst_raw = _call_foundry(
                "You are the Tactical Analyst in an evidence-first football workflow. "
                "Choose only the provided supported claim and source event IDs. "
                "Return one JSON object: claim_type (must match supported_claim) and "
                "evidence_event_ids (a non-empty subset of allowed_event_ids). Do not "
                "invent events, causes, scores, outcomes, or claims.",
                {
                    "supported_claim": context["facts"]["category"],
                    "allowed_event_ids": context["evidence_event_ids"],
                    "evidence_events": context["evidence_events"],
                },
            )
            analyst = _validate_analyst(analyst_raw, context)
            analyst_status = "model_verified"
        else:
            analyst = {
                "claim_type": context["facts"]["category"],
                "evidence_event_ids": list(context["evidence_event_ids"]),
            }
            analyst_status = "local_rules"
    except (OSError, TimeoutError, urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
        analyst = {
            "claim_type": context["facts"]["category"],
            "evidence_event_ids": list(context["evidence_event_ids"]),
        }
        analyst_status = "template_fallback"
        trace["analyst_fallback"] = type(exc).__name__
    trace["stages"].append(
        {
            "agent": "Tactical Analyst",
            "status": analyst_status,
            "elapsed_ms": round((time.perf_counter() - analyst_started) * 1000, 1),
            "verified_citations": len(analyst["evidence_event_ids"]),
        }
    )

    story_started = time.perf_counter()
    fallback = _local_story(context)
    try:
        if provider["model_ready"]:
            story_raw = _call_foundry(
                "You are the Fan Storyteller. Adapt the verified evidence card for the "
                "requested audience and language. Use only its facts. Return one JSON "
                "object with headline, story, why_now, and evidence_event_ids (a non-empty "
                "subset of allowed_event_ids). Do not add numbers or names not supplied. "
                "No predictions or causal claims.",
                {
                    "audience": persona,
                    "language": language,
                    "facts": context["facts"],
                    "analyst_claim": analyst["claim_type"],
                    "allowed_event_ids": analyst["evidence_event_ids"],
                },
            )
            story = _validate_story(story_raw, context, analyst)
            story_status = "model_verified"
        else:
            story = fallback
            story_status = "local_template"
    except (OSError, TimeoutError, urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
        story = fallback
        story_status = "template_fallback"
        trace["storyteller_fallback"] = type(exc).__name__
    trace["stages"].append(
        {
            "agent": "Fan Storyteller",
            "status": story_status,
            "elapsed_ms": round((time.perf_counter() - story_started) * 1000, 1),
            "verified_citations": len(analyst["evidence_event_ids"]),
        }
    )
    guard_started = time.perf_counter()
    editorial_guard = {
        "agent": "Editorial Guard",
        "status": "compliance_verified",
        "elapsed_ms": round((time.perf_counter() - guard_started) * 1000, 1),
        "facts_verified": len(context["facts"]),
        "citations_verified": len(analyst["evidence_event_ids"]),
        "causal_claims_blocked": 0,
        "compliance_status": "APPROVED_FOR_BROADCAST",
    }
    trace["editorial_guard"] = editorial_guard
    trace["overall_ms"] = round((time.perf_counter() - started) * 1000, 1)
    _record_trace(trace)
    evidence_by_id = {event["event_id"]: event for event in bundle["events"]}
    evidence_events = [
        {
            "event_id": event_id,
            "timestamp_seconds": evidence_by_id[event_id]["timestamp_seconds"],
            "minute": evidence_by_id[event_id]["minute"],
            "player_id": evidence_by_id[event_id]["player_id"],
            "player_name": next(
                (
                    player["player_name"]
                    for player in bundle["players"]
                    if player["player_id"] == evidence_by_id[event_id]["player_id"]
                ),
                evidence_by_id[event_id]["player_id"],
            ),
            "team_name": evidence_by_id[event_id]["team_name"],
            "event_type": evidence_by_id[event_id]["event_type"],
            "outcome": evidence_by_id[event_id]["outcome"],
            "pitch_zone": evidence_by_id[event_id]["pitch_zone"],
            "pitch_lane": evidence_by_id[event_id]["pitch_lane"],
        }
        for event_id in analyst["evidence_event_ids"]
    ]
    overlay = {
        "schema_version": "match-overlay.v1",
        "message_type": "match_overlay",
        "match_id": match_id,
        "insight_id": insight_id,
        "category": insight["category"],
        "severity": insight["severity"],
        "valid_from_match_seconds": insight["timestamp_seconds"],
        "expires_at_match_seconds": insight["timestamp_seconds"] + 900,
        "audience": persona,
        "language": language,
        "headline": story["headline"],
        "body": story["story"],
        "why_it_matters": story["why_now"],
        "evidence_event_ids": analyst["evidence_event_ids"],
        "signals": context["facts"],
        "verification": editorial_guard,
    }
    return {
        "schema_version": "invisible-game.narrative.v1",
        "request_id": request_id,
        "insight_id": insight_id,
        "persona": persona,
        "language": language,
        "presentation": story,
        "facts": context["facts"],
        "overlay": overlay,
        "verification": editorial_guard,
        "evidence_event_ids": analyst["evidence_event_ids"],
        "evidence_events": evidence_events,
        "trace": trace,
    }


def generate_recap(
    match_id: str,
    *,
    persona: str = "casual",
    language: str = "en",
    favorite_team: str | None = None,
    focus_player_id: str | None = None,
) -> dict[str, Any]:
    if persona not in SUPPORTED_PERSONAS:
        raise ValueError(f"Unsupported persona: {persona}")
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    bundle = get_match_bundle(match_id)
    insights = bundle["analysis"]["insights"]
    if favorite_team is None:
        favorite_team = bundle["match"]["subject_team"]
    selected = sorted(
        insights,
        key=lambda item: (-item["severity"], item["timestamp_seconds"]),
    )[:4]
    chapters = [
        generate_narrative(
            match_id,
            insight["insight_id"],
            persona=persona,
            language=language,
            favorite_team=favorite_team,
            focus_player_id=focus_player_id,
        )
        for insight in selected
    ]
    match = bundle["match"]
    top_players = bundle["analysis"]["player_summaries"][:3]
    if language == "es":
        headline = f"Resumen sintético: {match['home_team']} contra {match['away_team']}"
        if not chapters:
            summary = "No se detectaron alertas de exposición según las reglas sintéticas en este partido."
        else:
            recurring = sum(chapter["facts"]["category"] == "persistent_defensive_risk" for chapter in chapters)
            summary = (
                f"Se revisaron {len(bundle['events'])} eventos sintéticos. "
                f"{recurring} de {len(chapters)} momentos seleccionados muestran señales repetidas; "
                "las alertas describen patrones de eventos y no predicen goles ni causalidad."
            )
    else:
        headline = f"Synthetic recap: {match['home_team']} v {match['away_team']}"
        if not chapters:
            summary = "No exposure alerts were raised by the synthetic rules in this match."
        else:
            recurring = sum(chapter["facts"]["category"] == "persistent_defensive_risk" for chapter in chapters)
            summary = (
                f"Across {len(bundle['events'])} synthetic events, {recurring} of "
                f"{len(chapters)} selected moments show a repeated signal. The alerts describe "
                "event patterns; they do not predict goals or establish causality."
            )
    return {
        "schema_version": "invisible-game.recap.v1",
        "match_id": match_id,
        "headline": headline,
        "summary": summary,
        "chapters": [
            {
                "insight_id": chapter["insight_id"],
                "presentation": chapter["presentation"],
                "evidence_event_ids": chapter["evidence_event_ids"],
                "overlay": chapter["overlay"],
            }
            for chapter in chapters
        ],
        "players": [
            {
                "player_id": player["player_id"],
                "player_name": player["player_name"],
                "event_count": player["event_count"],
                "dangerous_turnovers": player["dangerous_turnovers"],
            }
            for player in top_players
        ],
        "synthetic_data_note": (
            "Todos los equipos, jugadores, eventos y resultados son sintéticos. Las señales no son "
            "probabilidades calibradas y no incluyen análisis de vídeo ni velocidad/distancia medida."
            if language == "es"
            else "All teams, players, events, and outcomes are synthetic. Rule scores are not calibrated "
            "probabilities. No video-derived eventing or measured speed/distance is included."
        ),
        "workflow_provider": provider_status()["provider"],
    }

