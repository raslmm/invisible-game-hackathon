# Invisible Game Hackathon

A fully synthetic football project focused on detecting persistent defensive risk and distinguishing repeated exposure from isolated dangerous moments.

The dataset contains 60 fictional matches, 17,280 events, 1,320 named players, 360 match windows, and 180 evaluation prompts. Its six core CSV files are in the data folder; see data/data_dictionary.json for field definitions.

The 60 matches are variations of 12 synthetic tactical archetypes, not independent real-world observations. Keep each match_id in a single evaluation split; group by scenario_type when evaluating transfer to unseen archetypes.

## Local event replay

Replay a short segment as versioned JSON Lines (JSONL), with one machine-readable event envelope per line:

```powershell
python scripts/replay_match.py --match-id IGM001 --speed 60 --limit 20
```

Use `--limit 0` for the full match or `--no-wait` to emit events immediately. Add `--interactive` for step-through controls: Enter advances, `p` pauses or resumes, `r` resets, `s 120` changes playback to 120x, and `q` exits. Events are ordered by source timestamp; duplicate event IDs are suppressed during each replay. Progress is written to stderr so stdout can be saved as a clean JSONL stream.

## Deterministic match analysis

Build a machine-readable summary for one synthetic match:

```powershell
python scripts/analyze_match.py --match-id IGM001
```

The `match-metrics.v1` output contains 15-minute windows, three five-minute exposure segments per window, pressure and event-rate summaries, defensive recovery and cover signals, named subject-team player summaries, and evidence-linked insights. Persistent risk requires an elevated composite signal plus recurrence in at least two five-minute segments. A concentrated dangerous moment is reported separately when the evidence does not establish a repeated pattern.

The composite score and thresholds are transparent synthetic heuristics, not calibrated probabilities or real-match accuracy claims. At runtime the analysis reads the event and roster CSVs, not the ground-truth labels. The current thresholds are provisional development heuristics; validate them on an archetype-grouped holdout before making performance claims. Event share is reported instead of possession-time share because the dataset has no possession-duration field.

Run the focused checks from the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

The `match-event.v1` event contract and `match-insight.v1` evidence contract are implemented in the local Python package. Requires Python 3.10 or newer; replay and analysis use only the standard library. No cloud service or language model is connected yet.