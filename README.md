# Invisible Game Hackathon

A fully synthetic football dataset for exploring persistent defensive risk and distinguishing repeated exposure from isolated dangerous moments.

The dataset contains 60 fictional matches, 17,280 events, 1,320 named players, 360 match windows, and 180 evaluation prompts. Its six core CSV files are in the data folder; see data/data_dictionary.json for field definitions.

The 60 matches are variations of 12 synthetic tactical archetypes, not independent real-world observations. Keep each match_id in a single evaluation split; group by scenario_type when testing transfer to unseen archetypes.
