# Phase 1 — Baseline Random Forest for Wildfire Crew Ranking

Record of the first phase: the question, the design decisions behind `model/train_rf.py` and the reasons for them, the runs and their results, how the implementation was verified, and the questions left for the next phase.

The rules below were given to an AI coding agent as the implementation prompt; this document restates them with their reasons.

- **Code:** commit `72304a8`
- **Status:** complete.
- Alternatives are listed only where one was considered.

## Question

Can a model that uses only information known at initial assessment rank wildfires so that more of the fires that later become large get a crew, compared with ranking by initial size alone?

---

## Decisions

### 1. Data source

**Rule:** Use only the official Open Alberta CSV (2006–2025, 27,828 fires). The organizer-provided sample is not used.

**Why:**
- The goal is to learn what makes a fire become large from long-term data. A short or sampled window is more easily distorted by sampling or by conditions specific to those years.
- The organizer sample covers only 2023–2025 and is not a complete record, so I was concerned it would bias the model.
- The full history allows comparing a long and a recent training window (decision 4).

**Basis:**
- The sample is a subset of the official file (all 856 rows match exactly). It keeps all C/D/E fires but only ~12–13% of A/B fires, so its large-fire rate is 20.0%, compared with 4.7% in the official 2023–2025 data.
- The sample lacks `ASSESSMENT_DATETIME` (needed for the allocation day), `FIRE_POSITION_ON_SLOPE` and `WEATHER_CONDITIONS_OVER_FIRE`.
- Official data, large-fire rate: ~1.5% in 2006–2022 vs 4.7% in 2023–2025.

**Known limitation:** large fires are rare in the long-term data, so the positive class is small.

### 2. Label: large fire = final area > 200 ha

**Rule:** `y = 1 if CURRENT_SIZE > 200 else 0`. `CURRENT_SIZE` is the final burned area; it is used only for the label and for evaluation, never as a feature.

**Why:**
- 200 ha is the boundary of Alberta's size class E, the largest class in the data dictionary (p.6). The dictionary does not define "large fire" itself.
- More than 200 ha is the national definition of a large fire in Canada, used by the Canadian Large Fire Database (Stocks et al., 2002).
- These fires cause almost all of the damage: nationally 3.5% of fires but ~97% of area burned (1959–1997); in this dataset (2006–2025), 1.89% of fires but 99.17% of area burned.

**Known limitation:** final areas can be revised after extinguishment; fires mapped by aerial photography are usually updated the following spring (dictionary p.6). No such revision is visible in this file: for fires over 100 ha, final area equals extinguished area in every year.

**Sources:**
- Alberta Historical Wildfire Data Dictionary 2006–2025, p.6.
- Stocks, B. J. et al. (2002). Large forest fires in Canada, 1959–1997. *Journal of Geophysical Research: Atmospheres*. https://doi.org/10.1029/2001JD000484
- Dataset area share: computed from the official CSV.

### 3. Features

**Rule:** Use only these 10 features; every other column is forbidden.
- Numeric: `ASSESSMENT_HECTARES`, `FIRE_SPREAD_RATE`, `TEMPERATURE`, `RELATIVE_HUMIDITY`, `WIND_SPEED`
- Categorical: `FIRE_TYPE`, `FUEL_TYPE`, `FIRE_POSITION_ON_SLOPE`, `WEATHER_CONDITIONS_OVER_FIRE`, `FOREST_AREA`

**Why:**
- The ranking is made at initial assessment, so the model may only use information available then. Anything recorded later would leak the outcome.
- Each feature is documented as recorded at the time of initial assessment (dictionary p.12). `FOREST_AREA` is the first letter of `FIRE_NUMBER`, assigned from the ignition area (p.5).
- Together they cover fire size and behaviour, weather, fuel, position on slope and region.

**How the list was made:** drafted with AI assistance in the implementation prompt, then checked field by field against the data dictionary.

**Excluded fields that are known at or before assessment:**
- `DISCOVERED_SIZE`: missing for 99.5% of fires.
- `WIND_DIRECTION`: its effect on spread depends on whether the wind blows upslope, which requires slope aspect. The data records position on slope but not aspect, and 73% of fires are on flat ground. `WIND_SPEED` is included.
- `LATITUDE` / `LONGITUDE`: may be revised after investigation; the stored value is the confirmed ignition point (p.6).
- `GENERAL_CAUSE`: fires under investigation carry a temporary cause (p.7); the stored value is the final cause.
- `FIRE_START_DATE`: often estimated; for lightning fires it is reconstructed from lightning map data (p.10).

**Known limitation:** every feature is a single snapshot at initial assessment (p.12); later changes in weather or fire behaviour are not captured.

### 4. Time split and training windows

**Rule:**
- Train on `train_start ≤ YEAR ≤ train_end`, test on `YEAR == test_year`, with `train_end < test_year`.
- 2024 is the development test year. 2025 is reserved for one final run and requires `--final`.
- Two training windows are compared on 2024: full (2006–2023) and recent (2022–2023, the two years immediately before 2024).

**Why:**
- Training only on earlier years matches real use: the model is always applied to a season it has not seen.
- Repeatedly checking results on a test year and adjusting the design would overfit to it, so 2025 is used once, at the end.
- 2024 is the most recent full year before 2025 and had 63 large fires, enough positives for development.
- Comparing the two windows tests whether recent years differ from the long-term history.

**Known limitations:**
- Development decisions rest on a single test year (2024).
- The recent window is dominated by one year: 68 of its 97 large fires are from 2023, the year with the most large fires in 2006–2025.
- Fires that burn into the following year are common (3–97 per year in 2006–2024, all with complete records). In 2025, 16 fires (13 over 100 ha) had no extinguished record when the data was exported, most likely holdover fires still burning, so their final areas may still change. Planned: report the final 2025 evaluation both with and without these fires; add this rule before the `--final` run.
- No model has been evaluated on 2025.

### 5. Model

**Rule:** `RandomForestClassifier(n_estimators=500, random_state=42, n_jobs=-1)`, other parameters at their defaults, no tuning. The score is `predict_proba(X)[:, 1]`.

**Why:**
- Chosen on the advice of an experienced ML practitioner.
- A random forest needs no feature scaling, handles non-linear effects and interactions (for example high temperature with low humidity), and works directly on one-hot categories.
- No tuning: the only validation year is 2024, and tuning on it would overfit the design to 2024.

**Alternatives considered:** logistic regression, not pursued; the random forest was chosen on advice.

**Known limitations:**
- The model learns from both classes, but only 422 large fires (against ~24,900 that stayed small) show the varied ways a fire becomes large; that smaller class limits what the model can learn. Using only the ranking avoids relying on uncalibrated probabilities but does not remove this limit.
- `feature_importances_` (impurity-based) favours numeric features and spreads each categorical feature across its one-hot columns, so it does not reliably show which factors matter most ([scikit-learn documentation](https://scikit-learn.org/stable/auto_examples/inspection/plot_permutation_importance.html)).

### 6. Ranking order

**Rule:**
- RF ranking: RF probability (high → low) → `ASSESSMENT_HECTARES` (high → low) → `FIRE_SPREAD_RATE` (high → low) → `fire_id` (A → Z). Tie-breaks use raw values (before median filling); missing values go last.
- Baseline ranking: the same order without the RF probability (decision 9).

**Why:**
- On equal probability, prefer the fire that is already larger, then the one spreading faster. In the exploratory analysis (`research/explore.py`, Q3; written with an AI coding agent and reviewed by me), these were the strongest single signals: median per-year AUC 0.92 (area) and 0.91 (spread rate) over 2006–2015, lowest year 0.82 for both, against 0.70–0.72 for temperature, wind speed and dryness. Area is marginally higher, so it comes first.
- `fire_id` only makes results reproducible; it does not mean priority.
- Sharing the tie-breaks means the RF and baseline rankings differ only in whether the RF score is used.

**Known limitation:** ties occur. On 2024-07-16, ranks 9 and 10 (`LWF141`, `LWF151`) have identical features and probability, so `fire_id` alone decides their order.

### 7. Crew availability `H` as an operational input

**Rule:** one crew per fire. `H` is a runtime input; the model and the ranking stay fixed, and only the allocation cutoff moves when `H` changes.

**Why:**
- How dangerous a fire is and how many crews are available today are independent questions, so the ranking should not change with the crew count.
- One crew per fire is a deliberate simplification. The task is to rank fires; deciding how many crews each fire needs would make it a resource-optimization problem, which is out of scope.

**Known limitation:** in practice a large fire may need several crews. The allocation counts fires that receive a crew, not the effort each fire requires.

### 8. Crew cut: `H_cut = floor(0.8 × H)`

**Rule:** crews fall by 20%, rounded down. Ranks 1 to `H_cut` → `kept`; ranks `H_cut + 1` to `H` → `displaced`; the rest → `no_crew`.

**Why:**
- The challenge asks to "cut crews by 20% and rebuild the list. Report which fires lost a crew" (README); the starter code uses `int(N * 0.8)`.
- Rounding down is conservative: rounding up would assign a crew that does not exist.
- "Rebuild the list" is done by moving the cutoff. Since the ranking does not depend on the crew count (decision 7), a rebuilt list has the same order.

**Known limitation:** the cut is exactly 20% only when `H` is a multiple of 5; for small `H` it is larger (`H = 4` → 25%, `H = 2` → 50%, `H = 1` → 100%).

### 9. Baseline: largest first

**Rule:** the RF ranking without the probability step (decision 6).

**Why:**
- The challenge defines it: "Beat 'largest area first'" (README).
- Initial area is the strongest single signal (decision 6), so this is a demanding baseline, not a weak one.

**Known limitation:** the starter code scores fires with `CURRENT_SIZE`, the final area, which is not known at assessment. This baseline uses `ASSESSMENT_HECTARES`, so its numbers are not directly comparable with the starter's.

### 10. Evaluation

**Rule:**
- Whole test year: RF ROC-AUC and average precision; baseline ROC-AUC (score = `ASSESSMENT_HECTARES`); top-K hits for both rankings, K = number of large fires in the test year (63 in 2024).
- One allocation day (2024-07-16): the fires first assessed that day are re-ranked; count large fires among the top `H` and top `H_cut` of each ranking.

**Why:**
- The whole year tests whether the model has learned what makes a fire become large; the allocation day tests an actual crew decision, closer to the challenge's "next-crew list".
- K = number of large fires (suggested by the AI coding agent): a perfect ranking places exactly the K large fires in the top K.
- The allocation day was picked from days with many fires (49 fires, 10 large).

**Known limitation:** the allocation result comes from one day picked without a fixed rule, so it depends on which day was chosen.

### 11. Displaced fires: comparison, not explanation

**Rule:**
- For each displaced fire (RF ranking only), print its rank, probability, `H` and `H_cut`, and every feature side by side with the last kept fire (rank `H_cut`). If `H_cut = 0`, there is no last kept fire, so the side-by-side is skipped.
- The output is labelled "Comparison". It must not claim that a single feature caused the lower rank; the only stated reason is "ranked #X; after crews fell from H to H_cut, only ranks 1–H_cut keep a crew."

**Why:**
- A random forest combines many trees, so it cannot honestly say a fire ranked lower *because* of one feature. A wrong reason misleads a crew decision.
- Phase 1 has not shown that the RF ranking beats the baseline consistently (see Results), so attaching reasons to it would overstate it.

**Known limitation:** the challenge asks for "a reason you can say out loud" (README). How to give an honest reason is still open.

### 12. Reproducibility: pinned package versions

**Rule:** `requirements.txt` pins pandas 2.3.2, numpy 2.2.2 and scikit-learn 1.7.2.

**Why:** both teammates get identical results from the same command. Together with the fixed `random_state` (decision 5), every run is reproducible.

**Known limitation:** the Python version is not pinned.

---

## Runs and results

`outputs/` is git-ignored, so the numbers below are the durable record.

```
python model/train_rf.py --train-start 2006 --train-end 2023 --test-year 2024 --crews 10 --allocation-date 2024-07-16 --run-name dev_full
python model/train_rf.py --train-start 2022 --train-end 2023 --test-year 2024 --crews 10 --allocation-date 2024-07-16 --run-name dev_recent
```

`dev_full` was run by Anni and `dev_recent` by a teammate.

| Metric (test year 2024) | `dev_full` (2006–2023) | `dev_recent` (2022–2023) | Baseline |
| --- | --- | --- | --- |
| Training fires / large | 25,321 / 422 | 2,408 / 97 | — |
| ROC-AUC | 0.955 | 0.947 | 0.909 |
| Average precision | 0.618 | 0.598 | — |
| Top 63 hits (whole year) | 38 | 37 | 34 |
| 2024-07-16 hits at `H = 10` | 3 | 5 | 7 |
| 2024-07-16 hits at `H_cut = 8` | 3 | 5 | 6 |

**Observations:**
- Over the whole year, both RF runs beat the baseline. On 2024-07-16, both catch fewer large fires than the baseline. The two levels point in opposite directions.
- On 2024-07-16, some fires that became large and were already 5–7 ha at assessment rank low in the RF ranking (`LWF159` #14, `LWF152` #25) but near the top of the baseline ranking (#2 and #3).
- The two training windows give similar whole-year results (38 vs 37 hits). These runs do not show whether either window is better.

---

## Verification

| Check | Result |
| --- | --- |
| Expected counts from the implementation prompt | All match: no duplicate `fire_id`; training 25,321 / 422 large (2006–2023) and 2,408 / 97 (2022–2023); 2024: 1,230 fires / 63 large; 2024-07-16: 49 fires / 10 large; with `H = 10`: 8 kept / 2 displaced / 39 no crew; baseline 34 / 7 / 6 (top 63 / `H` / `H_cut`) |
| Reproducibility | Rerunning both commands at `72304a8` gives the same results. `dev_full` was first run shortly before the commit; its rerun outputs are byte-identical. |
| Code vs implementation prompt | Every rule checked against the code; no deviations found (AI review only) |

---

## Open questions for phase 2

1. **Is one allocation day representative?** The whole-year and single-day results disagree (decision 10). Evaluating across many days would need its selection rules fixed before looking at results.
2. **Scope of the allocation day.** Only fires first assessed that day are ranked; fires assessed earlier and still burning are not included. If kept, `H` should be stated as the crews available for newly assessed fires.
3. **Long vs recent training window.** The phase 1 runs do not separate them (Results).
4. **An honest reason that can be said out loud** for each ranking decision (decision 11).
5. **Minimum `H`**, given that rounding down cuts more than 20% for small `H` (decision 8).
6. **Handling of 2025 holdover fires**, to be fixed before the `--final` run (decision 4).

---

## Appendix — Implementation choices not specified in the implementation prompt

- `ASSESSMENT_DATETIME` values that cannot be parsed become missing (`errors="coerce"`), so those fires are silently left out of the allocation day. The current data has none.
- The code passes `kind="mergesort"`, but pandas ignores `kind` when sorting on several columns. The order is still fully determined because the last tie-break, `fire_id`, is unique.
