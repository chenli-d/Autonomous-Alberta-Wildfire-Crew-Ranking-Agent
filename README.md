# Case 3 - Which wildfires get the next crew?

**Stream:** Software and Computational Math  
**Event:** IEEE YP Industry Hackathon  
**Dates:** October 2–4, 2026 | Collision Space, Hunter Hub, University of Calgary

---

## The problem (in plain words)

Alberta does not have infinite crews or air tankers. If you always send the next crew to the **biggest** fire, a smaller fire that is spreading fast in wind can wait. That trade-off was expensive in 2023–2025: the Jasper fire was about **$1.1 billion** in insured losses, and 2025 fires shut in about **7% of Canadian oil** at the peak.

This is a **ranking** problem. You are not simulating fire spread.

**Your challenge:** Rank fires for a limited number of crews. Beat “largest area first.” Then cut crews by **20%** and rebuild the list. Report which fires lost a crew.

You ranked fires. You did **not** put the fire out.

---

## Who would use this

An Alberta Wildfire duty officer. You are selling the **next-crew list** when capacity drops, with a reason you can say out loud.

---

## Steps

1. Load the 2023–2025 fire table. Drop rows missing size or coordinates. Say how many.
2. Score each fire in one line (example: size × wind × dryness, or size + spread rate).
3. Give `N` crews (starter: 40). Baseline = largest size first.
4. Set `N` to 80%. Which fire numbers dropped?
5. Duty-officer paragraph: why these fires, what you skipped.

---

## Picture of the loop

```mermaid
flowchart LR
  A[Load fires] --> B[Score size + weather]
  B --> C[Fill N crews]
  C --> D[20% fewer crews]
  D --> C
```

A **hectare** is 10,000 m² - a bit larger than a soccer pitch.

---

## New words

| Word | Meaning |
|---|---|
| Size class | Alberta’s letter for how big the fire is (A small → E very large) |
| Spread rate | How fast the fire is growing |
| Baseline | Biggest fire first |

---

## Watch or read (optional)

- [Alberta wildfire status](https://www.alberta.ca/wildfire-status)
- [How wildfires grow (simple overview, U.S. National Weather Service)](https://www.weather.gov/safety/wildfire)
- Open data used here: Alberta historical wildfire CSV (see [`data/README.md`](data/README.md))

---

## Start here

1. Open a terminal **in this folder**.
2. `pip install -r requirements.txt`
3. `python agent_starter.py`
4. Change `N` or the score formula and run it again.

Data notes: [`data/README.md`](data/README.md). **Python 3.10+** (3.11 is best).

## Community proximity map

This standalone app shows the nearest five Alberta communities to one wildfire.
It does not run or change the wildfire model, score hazards, or provide response advice.
The assessment-date selector currently supports **2024-07-16 only**. The main
ranking source is `outputs/dev_recent/ranking_2024.csv`, loaded without running or
modifying the model. Its original `rank`, `rf_probability`, and `baseline_rank`
values are preserved; ranks are not recalculated for the day.

Ranking rows are joined to the existing official local file
`data/raw/fp-historical-wildfire-data-2006-2025.csv` using
`fire_id == str(YEAR) + ":" + FIRE_NUMBER.strip()`. Coordinates come exclusively
from that official file. A ranking `assessment_date` column is used when present;
otherwise the date is derived from official `ASSESSMENT_DATETIME`. Only July 16
records are shown. No fire-start-date fallback is used. The bundled subset is no
longer used for this UI. Both input files are required locally and remain excluded
from Git; the app performs no wildfire-data download. Their modification times
invalidate the data cache.

The daily ranking table shows 49 matching fires with the current inputs. Select a
fire from the dropdown to view a grouped detail card and its community-proximity
map/table/JSON. The overview shows all valid locations without community lines.
Missing fields display `N/A`; missing/invalid coordinates keep the fire in the
ranking table and card but disable its maps/proximity lookup. Unmatched IDs and
invalid assessment dates are reported; ambiguous duplicate IDs produce an error.

### Crew-cut review candidates

This section is a deterministic shortlist for later review, not a new ranking or
allocation. Saved context comes from `outputs/dev_recent/allocation_2024-07-16.csv`
(only fire ID, daily rank, and status) and `outputs/dev_recent/metrics.json`
(only allocation date, `H`, and `H_cut`). The current run has `H=10`, `H_cut=8`.
The ranking table preserves annual RF ranks; the shortlist also shows the saved
daily allocation RF ranks used for crew cutoffs. Neither is recalculated.

Select daily rank `H_cut` as `last_kept`, ranks `H_cut+1` and `H_cut+2` as
`cutoff_boundary`, and the two closest fires whose saved status is `displaced`
or `no_crew` as `proximity_exception`. Only finite, nonnegative distances qualify
for proximity selection; ties sort by fire ID. Deduplicate IDs and keep every
applicable reason. Display last kept first, then boundary fires by daily rank,
then remaining proximity exceptions by distance. Fewer eligible fires produce
a shorter shortlist. Missing community data leaves boundary candidates available.

Allocation context must match the displayed fire IDs completely, with unique
consecutive daily ranks, consistent saved statuses, and valid crew counts/date.
Missing or inconsistent context hides the shortlist with a warning while retaining
the fire UI. Both context files' modification times invalidate its cache.
Community refresh recomputes candidate selection. `app/review_service.py` handles
loading/selection without mutating source records. No LLM, rescoring, crew swaps,
or allocation changes are performed; outcome fields are excluded.

Frontend records use an explicit allowlist of ranking, initial-assessment, weather,
fire-characteristic, date, and coordinate fields. `status` is included only when
present in the ranking source. `y`, `CURRENT_SIZE`, and unlisted future-outcome
fields are removed before caching or displaying records. The app shows inputs and
ranking values without causal explanations. Map marker scores use the existing
`rf_probability` value unchanged.

From this folder, using a working Python 3.10+ installation:

```powershell
$mapEnv = Join-Path $env:LOCALAPPDATA 'wildfire-map-venv'
python -m venv $mapEnv
& "$mapEnv\Scripts\python.exe" -m pip install -r requirements.txt
& "$mapEnv\Scripts\python.exe" -m streamlit run streamlit_app.py
```

Open the local URL printed by Streamlit. Select a day and wildfire, inspect
the map and table, and download the result JSON. `Refresh community data` retries
failed requests and clears the one-hour successful-data cache. Internet access is
required for the Alberta API and OpenStreetMap tiles. Partial lookups are explicitly
marked incomplete; complete failure still displays the fire marker.
The environment is deliberately placed outside the deeply nested repository path
to avoid Windows native-library path-length errors. If your existing `.venv` points
to an unavailable Python installation, use the fresh environment above.

Community geometries come exclusively from the [Alberta Government municipal
communities service](https://geospatial.alberta.ca/titan/rest/services/boundaries/municipal_communities_public/MapServer).
This UI queries **layer 0 only: Hamlet, Locality, Townsite**, using `/0/query` with
`where=1=1`, selected name/ID/type fields, `outSR=4326`, `returnGeometry=true`, and
`f=geojson`. Metadata supplies field names; records are paginated in object-ID order.
Only named, finite, in-range Point geometries are accepted. There are no hardcoded
fallback community coordinates. Cities and towns available as municipal polygons
are excluded from this point dataset; "nearest community" means nearest within
this layer's coverage. The reusable API fetcher still supports its original layer
selection for other callers.

Every displayed fire receives `nearest_community`, `nearest_community_distance_km`,
and `community_proximity_rank`. Haversine distance uses Earth radius 6371.0088 km,
using official fire coordinates and the API's actual community point coordinates.
The minimum unrounded distance determines the nearest point; community ties sort
by name, then source ID. Separate sequential proximity ranks sort by unrounded
distance, then fire ID. RF ranks, probabilities, and table order are unchanged.
This is not travel distance, exposure scoring, or a combined ranking.

The daily table compares distances/ranks, and the selected-fire card includes all
three fields. The selected-fire map uses the same points and shows its nearest five
with point-to-point lines, without municipal boundaries or centroid approximations.
Distances display to two decimal places; frontend records retain full precision.
Missing/invalid fire coordinates, unavailable data, or an empty usable point dataset
produce `None` in proximity fields and `N/A` in the UI; no proximity rank is assigned.
Invalid community rows are ignored. Refresh recalculates all fire enrichment and
selected-fire results against the refreshed points. Current point data is used for
historical fires. The original polygon-distance helper remains available for other
callers, but this UI does not use it.

Modules: `app/community_service.py` handles retrieval/normalization, `app/geo.py`
handles distances/results, `app/proximity_service.py` enriches ranked fires, and `app/map_view.py` creates the map.

Run the offline test suite:

```powershell
& "$mapEnv\Scripts\python.exe" -m unittest discover -s tests -v
```

For a live smoke check, launch the app with the default sample, confirm five rows
and corresponding proximity map features, plus 49 fire records and overview markers.
Confirm the assessment-date selector has only July 16, change the wildfire selector,
inspect its detail card, and test `Refresh community data`. Offline tests cover the
ID join, date filter, field allowlist, missing values/coordinates, selection, geometry,
pagination, empty layers, and partial/network failures. A local-input test checks the
49 real records and unchanged ranks. Point-enrichment tests cover known distances,
invalid coordinates, deterministic ties, separate proximity ranks, and refresh.

### Bounded AI boundary review

The optional agent review uses OpenAI Chat Completions with strict JSON Schema,
default model `gpt-4.1-mini` (`OPENAI_MODEL` can override it). It uses the existing
`requests` dependency. Configure `OPENAI_API_KEY` in the environment that launches
Streamlit, then restart the server. The app also automatically loads the project-root
`.env` using `python-dotenv`; existing process variables take precedence. Install
updated requirements before restarting. Put `OPENAI_API_KEY` and optionally
`OPENAI_MODEL=gpt-4.1-mini` in that local file. `.env` and `.env.*` are Git-ignored;
keys stay server-side and are never included in prompts, UI tables or trace downloads.
Do not commit credentials or paste them into chat.
For a session-only PowerShell setup without putting the key in command history:

```powershell
$reviewSecret = Read-Host 'OpenAI API key' -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', $reviewSecret).Password
Remove-Variable reviewSecret
& "$mapEnv\Scripts\python.exe" -m streamlit run streamlit_app.py
```

`Run agent review` sends one request, with a 10-second connection timeout and
60-second read timeout, no tools and no automatic retries. Missing credentials
disable the button. API failure, refusal, incomplete output, or invalid JSON
preserves the original allocation. The agent receives only the last-kept fire and
shortlisted no-crew challengers: IDs, annual/daily RF ranks, probability, baseline
rank, initial assessment/weather/fire-characteristic fields, nearest community,
distance, proximity rank, review reasons and saved status. Coordinates and arbitrary
source columns are excluded, including `y`, `CURRENT_SIZE` and future outcomes.

The exact response keys are `decision`, `promote_fire_id`, `displace_fire_id`,
`reason`, and `evidence`. `KEEP_ORIGINAL` requires null IDs. A `SWAP` must promote
one shortlisted `displaced`/`no_crew` fire and displace only the saved last-kept fire.
Code independently validates the response and simulates two changed crew flags
(one crew transfer), with exactly `H_cut` assignments and no rank/status mutations.
The prompt prefers keeping RF allocation when evidence is ambiguous; proximity
alone is insufficient, and no numeric thresholds or causal RF explanations are invented.

A valid swap is a proposal until you click **Apply swap**. Application revalidates
the proposal and changes a separate session-only crew-assignment map. The UI shows
before/after assignments and final allocation alongside unchanged saved statuses.
Saved CSVs and RF ranks are never rewritten. Apply is disabled after application.
A new review starts from saved allocation; community Refresh, source-file changes,
or model/input changes invalidate the review and restore original session allocation.

`Download agent review trace` preserves sanitized input, policy/version, model,
raw structured response, validation result and final assignments/action. No API
keys or headers are included. Trace/session state lasts only for the browser session
unless downloaded. `app/agent_review.py` isolates the API, `app/agent_validation.py`
validates/applies copies, and `app/agent_view.py` implements the explicit review UI.
Offline tests mock KEEP, SWAP, invalid/API failures, missing credentials, explicit
application and stale-review handling. A live decision requires a configured API key;
it is not inferred from offline test responses.
