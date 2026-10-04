# Phase 2 — Multi-day and Multi-year Evaluation

Record of the second phase, in the order the work was done: the questions carried over from [phase 1](phase-1.md), each step's decisions and reasons, the runs and their results, and the work still open.

- **Code:** commit `3c4ec8a` (`model/evaluate_days.py`, `research/diagnose_days.py`, `model/rolling_eval.py`)
- **Status:** in progress.

## Questions

1. Does the RF ranking catch more large fires than "largest first" when crews are allocated day by day, not just on one hand-picked day? (phase 1, open question 1)
2. Does the long or the recent training window give better results? (phase 1, open question 3)

---

## Step 1 — Multi-day evaluation on 2024

### Decision

**Rule:**
- Test year 2024. `H` takes the values 5, 10, 15 and 20; `H_cut = floor(0.8 × H)`.
- **Own day sets:** for each `H`, every assessment day with more than `H` newly assessed fires.
- **Common day set:** every `H` evaluated on the same days, those with more than 20 newly assessed fires.
- On each selected day, that day's fires are ranked with the RF ranking and the baseline ranking (phase 1, decision 6). Large fires are counted among the top `H` and the top `H_cut` of each ranking.
- Reported per day set and `H`: total hits for RF and baseline, and the number of days RF wins, loses and ties. Ties are also reported separately for days with at least one large fire.
- Roles of the results: own day sets with `H = 10` are the **primary result**; `H` = 5, 15, 20 are sensitivity checks; the common day set is diagnostic only.
- All results are reported for both training windows, full (2006–2023) and recent (2022–2023).

**Why:**
- Phase 1's whole-year and single-day results disagree, and the single day was picked without a fixed rule (phase 1, decision 10).
- "More than `H`" fires: on a day with exactly `H` fires, every fire gets a crew, so both rankings tie and the day carries no information.
- `H = 10` matches phase 1. All four values are multiples of 5, so each cut is exactly 20% (phase 1, decision 8).
- The sensitivity checks show whether the conclusion depends on the assumed crew count, which we have no data for.
- In the own day sets, `H` and the days change together. The common day set holds the days fixed, so only `H` changes; comparing `H = 10` across the two day sets holds `H` fixed, so only the days change.
- Running both training windows costs almost nothing and gives evidence for question 2.
- The rule was fixed before any RF or baseline hits were computed. Only the number of qualifying days was checked beforehand:

| Day rule (2024) | Days | Days with ≥ 1 large fire | Fires | Large fires |
| --- | --- | --- | --- | --- |
| More than 5 fires | 60 | 24 | 825 | 60 |
| More than 10 fires | 30 | 18 | 594 | 52 |
| More than 15 fires | 14 | 9 | 391 | 40 |
| More than 20 fires | 9 | 6 | 300 | 31 |

**Known limitations:**
- In the own day sets, differences across `H` mix the effect of `H` with the effect of the days.
- The common day set has 9 days (6 with a large fire), too few to support a conclusion on its own; the same holds for `H = 20` in the own day sets, which uses the same 9 days.
- One test year (2024).

### Runs

```
python model/evaluate_days.py --train-start 2006 --train-end 2023 --test-year 2024 --run-name q1_full
python model/evaluate_days.py --train-start 2022 --train-end 2023 --test-year 2024 --run-name q1_recent
```

### Results

Primary result (own day sets, `H = 10`, 30 days, 52 large fires):

| | RF hits | Baseline hits | RF wins / losses / ties (days) |
| --- | --- | --- | --- |
| Full window, top `H` | 38 | 42 | 0 / 1 / 29 |
| Full window, top `H_cut` | 38 | 39 | 2 / 1 / 27 |
| Recent window, top `H` | 39 | 42 | 1 / 3 / 26 |
| Recent window, top `H_cut` | 39 | 39 | 1 / 2 / 27 |

Sensitivity checks and diagnostic, top `H` hits (RF vs baseline):

| `H` | Full, own days | Recent, own days | Full, common 9 days | Recent, common 9 days |
| --- | --- | --- | --- | --- |
| 5 | 41 vs 45 | 43 vs 45 | 13 vs 17 | 15 vs 17 |
| 10 | 38 vs 42 | 39 vs 42 | 18 vs 22 | 19 vs 22 |
| 15 | 31 vs 33 | 34 vs 33 | 22 vs 25 | 26 vs 25 |
| 20 | 26 vs 27 | 26 vs 27 | 26 vs 27 | 26 vs 27 |

**Observations:**
- On most days both rankings catch the same large fires. In total the baseline catches as many or slightly more, at every `H`, in both windows and in both day sets, except recent window `H = 15` (34 vs 33).
- The two training windows give similar results; question 2 is still not separated.

**Verification:** on 2024-07-16 at `H = 10`, both runs reproduce phase 1 (full: RF 3 / 3, baseline 7 / 6; recent: RF 5 / 5, baseline 7 / 6); training counts match phase 1 (25,321 / 422 and 2,408 / 97).

---

## Step 2 — Diagnosing the 2024 differences

**Why:** step 1 showed the baseline level with or ahead of RF at every `H`, in both training windows and both day sets, while RF leads over the whole year (phase 1). Before changing the model, we checked where the two rankings actually differ: whether the gap is spread across many days or comes from a few fires.

**What was done:** for the full window, own day sets, `H = 10`, each of the 52 large fires was classified by which ranking put it in the top `H`.

```
python research/diagnose_days.py
```

| Picked by | Large fires |
| --- | --- |
| Both rankings | 37 |
| Baseline only | 5 |
| RF only | 1 |
| Neither | 9 |

**Findings:**
- All six differences are on 2024-07-16. On the other 29 days both rankings catch exactly the same large fires.
- Three of the five baseline-only fires (`LWF152`, `LWF156`, `LWF159`) belong to the Kettle River Complex, a lightning complex in the Lac La Biche forest area; `LWF157`, also baseline-only, has no complex name. The RF-only fire (`MWF086`) belongs to the Algar Lake Complex.
- The nine fires missed by both rankings were small at assessment (median 0.2 ha); four belong to the Kettle River Complex, two to the Rabbit Lake Complex, and three have no complex name.
- Fire type and fuel are not where the rankings differ: 49 of the 52 large fires burned in coniferous fuel, and 21 of the 25 crown fires were caught by both rankings.

**Conclusion:** the 2024 day-level gap between RF and baseline comes from one day, largely one lightning complex. 2024 alone cannot separate the two rankings.

---

## Step 3 — Rolling-origin validation, 2016–2023

### Decision

**Rule:**
- For each validation year Y from 2016 to 2023, train the phase 1 RF (unchanged) on 2006 to Y−1 and evaluate on Y.
- Each year uses the step 1 primary rule: days with more than 10 newly assessed fires, `H = 10`, `H_cut = 8`.
- **Per fire (primary):** large fires among the top `H` and top `H_cut`, summed over all years.
- **Per complex (secondary):** fires whose `FIRE_NAME` ends in "Complex" are grouped by year and complex name; other fires are their own group. A complex counts as caught if any of its large fires is picked on any qualifying day of that year.
- Results are reported per year and in total.

**Why:**
- Step 2 showed one year can be decided by one event. Several validation years, each predicted only from earlier years, average over many fire seasons.
- 2016 onward: the exploratory analysis behind phase 1, decision 6 used 2006–2015, so the validation years are kept separate from it; every fold has at least 10 training years.
- 2016–2023 gives 111 large fires on qualifying days, against 70 for 2021–2023 alone, of which 48 are from 2023.
- Per-complex counting tests whether a result rests on a single complex. `FIRE_NAME` is assigned after the fact, like the final size; it is used only for scoring, never as a feature.
- Sample sizes were checked before any model was run:

| Year | Days with > 10 fires | With ≥ 1 large fire | Large fires on those days |
| --- | --- | --- | --- |
| 2016 | 44 | 6 | 8 |
| 2017 | 29 | 6 | 7 |
| 2018 | 35 | 10 | 11 |
| 2019 | 28 | 9 | 15 |
| 2020 | 13 | 0 | 0 |
| 2021 | 37 | 9 | 11 |
| 2022 | 22 | 6 | 11 |
| 2023 | 27 | 15 | 48 |

**Known limitations:**
- Per-complex counting was added after the step 2 diagnostic. It is secondary; per fire remains the primary result.
- Complex names are incomplete: only fires of provincial significance are named (dictionary p.6), so some fires of one event count separately (for example `LWF157`).
- "Caught if any fire is picked" is a scoring simplification: one crew on one fire of a complex does not handle the whole complex.
- 2020 has no large fire on qualifying days and contributes nothing to day-level results.
- Training size grows across folds (10 years for 2016, 17 for 2023).
- No statistical test was run; per-year differences are small.

### Run

```
python model/rolling_eval.py --run-name rolling_phase1
```

### Results

Per fire, top `H`:

| Year | Large fires | Baseline | RF | RF − baseline |
| --- | --- | --- | --- | --- |
| 2016 | 8 | 6 | 8 | +2 |
| 2017 | 7 | 6 | 7 | +1 |
| 2018 | 11 | 10 | 10 | 0 |
| 2019 | 15 | 12 | 14 | +2 |
| 2020 | 0 | 0 | 0 | 0 |
| 2021 | 11 | 10 | 10 | 0 |
| 2022 | 11 | 8 | 11 | +3 |
| 2023 | 48 | 41 | 42 | +1 |
| **Total** | **111** | **93** | **102** | **+9** |

Totals (235 days, 111 large fires, 89 large-fire complexes or single fires):

| | Baseline | RF |
| --- | --- | --- |
| Per fire, top `H` | 93 | 102 |
| Per fire, top `H_cut` | 87 | 96 |
| Per complex, top `H` | 78 | 82 |
| Per complex, top `H_cut` | 73 | 79 |

**Observations:**
- At top `H`, RF is ahead in 5 years, level in 3 and behind in none. At top `H_cut`, RF is behind once (2021: 9 vs 10).
- Without 2023, RF still leads at top `H`: 60 vs 52.
- Per complex, RF still leads, so the result does not rest on one complex.
- 2024 (step 1) is the exception: 38 vs 42. Including 2024, RF leads 140 vs 135 at top `H`.

---

## Planned work (not yet decided)

- **Explanations (phase 1, open question 4):** SHAP values per fire as structured input; a template paragraph as the fallback; Gemini to write the duty-officer paragraph from that input, with every number in the output checked against the input. Details, including API key handling, not yet decided.
- **Boundary swaps at `N` / `N+1` / `N+2`:** being explored by a teammate.
- **Before the `--final` run:** handling of 2025 holdover fires (phase 1, open question 6); whether 2025 also gets per-complex scoring. Minimum `H` (phase 1, open question 5) is avoided as long as `H` is a multiple of 5.
- **Code cleanup:** `rolling_eval.py` and `evaluate_days.py` repeat the day-level counting; merge after submission.

## Open questions carried from phase 1

- **Scope of the allocation day** (phase 1, open question 2): only fires first assessed on a day are ranked; if kept, `H` should be stated as the crews available for newly assessed fires.
