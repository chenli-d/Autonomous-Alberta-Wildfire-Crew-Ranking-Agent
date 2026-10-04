"""Wildfire data exploration script (Case 3): prints findings in plain language.

Usage:
    python research/explore.py [CSV path]
Default path: data/raw/fp-historical-wildfire-data-2006-2025.csv
Data source: Open Alberta, "Historical wildfire data: 2006 to 2025"
             https://open.alberta.ca/opendata/wildfire-data (do not commit the CSV)

Uses only pandas and numpy. Each section prints the numbers and what they mean.
Only data up to LAST_YEAR is read; 2025 is reserved for the final evaluation.

Written to try out ideas before phase 1. Phase 1 (doc/phase-1.md) uses Q1, Q3 and Q4.
Q7 follows the challenge setup (40 crews per year), not the phase 1 evaluation.
DEV_YEARS is the exploration period; phase 2 validation starts in 2016 to stay separate.
Notes on formula weights and the historical_rate whitelist are from an earlier framing, unused.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CSV = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw/fp-historical-wildfire-data-2006-2025.csv")
BIG_HA = 200          # final area > 200 ha = large fire (= Alberta size class E, per the data dictionary)
N_CREWS = 40          # 40 crews per year (setting from the README)
CONIFER = {"C1", "C2", "C3", "C4", "C7"}  # coniferous fuels (spruce, pine)
DEV_YEARS = (2006, 2015)  # formula weights may only be chosen from the development period; 2016–2024 is the test period
LAST_YEAR = 2024      # 2025 is reserved for the final evaluation and is never read here


def stars(auc: float) -> str:
    """Convert AUC to a star rating for readability. 0.5 = random guess, 1.0 = perfect."""
    return "★" * max(0, min(5, int(round((auc - 0.5) / 0.1)))) or "-"


def auc(y: np.ndarray, s: np.ndarray) -> float:
    """Probability that a randomly chosen large fire scores higher than a randomly chosen non-large fire."""
    r = pd.Series(s).rank().to_numpy()
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    return (r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> None:
    d = pd.read_csv(CSV, low_memory=False, encoding_errors="replace")
    d = d[d.YEAR <= LAST_YEAR].copy()
    n_cols = d.shape[1]
    for c in ["CURRENT_SIZE", "ASSESSMENT_HECTARES", "FIRE_SPREAD_RATE", "WIND_SPEED",
              "TEMPERATURE", "RELATIVE_HUMIDITY"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    for c in ["REPORTED_DATE", "DISPATCH_DATE", "ASSESSMENT_DATETIME", "FIRE_FIGHTING_START_DATE"]:
        d[c] = pd.to_datetime(d[c], errors="coerce")
    d["big"] = (d["CURRENT_SIZE"] > BIG_HA).astype(int)   # the answer: for evaluation only, never an input
    d["fire_type"] = d["FIRE_TYPE"].astype(str).str.strip()
    d["fuel"] = d["FUEL_TYPE"].astype(str).str.strip()

    section("[Q0] How much data is there?")
    print(f"{len(d):,} fires, {n_cols} columns, years {d.YEAR.min()}–{d.YEAR.max()}")
    print("Fires per year:", d.groupby("YEAR").size().to_dict())

    section("[Q1] How many large fires (final area > 200 ha, class E) are there?")
    print(f"Total: {d.big.sum():,} fires, {d.big.mean():.1%} of all fires")
    print("Large fires per year:", d.groupby("YEAR").big.sum().to_dict())
    print("→ Large fires are rare, so 'how many large fires the top 40 catch' is a strict test.")
    print("→ In the Case 3 sample, large fires are 20%, about 4 times the real rate, so we use the full data instead.")

    section("[Q2] Actual workflow: is a crew dispatched first, or is the fire assessed first?")
    t = d.dropna(subset=["REPORTED_DATE", "DISPATCH_DATE", "ASSESSMENT_DATETIME"])
    before = (t.DISPATCH_DATE <= t.ASSESSMENT_DATETIME).mean()
    mins = (t.ASSESSMENT_DATETIME - t.REPORTED_DATE).dt.total_seconds().median() / 60
    print(f"{before:.1%} of fires had the first crew dispatched before assessment; median time from report to assessment: {mins:.0f} minutes")
    print("→ 'Information at assessment' only exists after the first crew arrives. Our task is to decide where the next crew goes.")

    dev = d[(d.YEAR >= DEV_YEARS[0]) & (d.YEAR <= DEV_YEARS[1])]
    section("[Q3] Which information at assessment is most related to becoming a large fire? (development period 2006–2015 only, computed per year, median)")
    print("(Q3 and Q4 use only the development period because formula weights are chosen from them; looking at the test period would be peeking at the exam.)")
    print("Note: AUC = probability that this field ranks a randomly chosen large fire above a randomly chosen non-large fire. 0.5 = random guess")
    feats = {
        "Assessed area ASSESSMENT_HECTARES": dev.ASSESSMENT_HECTARES,
        "Spread rate FIRE_SPREAD_RATE": dev.FIRE_SPREAD_RATE,
        "Temperature TEMPERATURE": dev.TEMPERATURE,
        "Wind speed WIND_SPEED": dev.WIND_SPEED,
        "Dryness (100 - humidity)": 100 - dev.RELATIVE_HUMIDITY,
    }
    for name, col in feats.items():
        vals = []
        for _, g in dev.assign(x=col).dropna(subset=["x"]).groupby("YEAR"):
            if g.big.nunique() == 2:
                vals.append(auc(g.big.to_numpy(), g.x.to_numpy()))
        print(f"  {name:36s} median {np.median(vals):.2f} (min {min(vals):.2f}, max {max(vals):.2f}) {stars(np.median(vals))}")
    print("→ Area and spread rate are the most useful and stable every year; wind, temperature and dryness are secondary signals.")

    section("[Q4] Do fire type, fuel and region make a difference? (development period 2006–2015 only)")
    ft = dev[dev.fire_type.isin(["Crown", "Surface", "Ground"])].groupby("fire_type").big.agg(["mean", "size"])
    for k, r in ft.iterrows():
        print(f"  {k:8s}: {int(r['size']):6,} fires, {r['mean']:.1%} became large")
    print(f"→ Crown fires become large about {ft.loc['Crown', 'mean'] / ft.loc['Surface', 'mean']:.0f} times as often as surface fires.")
    dev = dev.assign(is_conifer=dev.fuel.isin(CONIFER))
    known = dev[dev.fuel.notna() & (dev.fuel != "nan")]
    cf = known.groupby("is_conifer").big.mean()
    print(f"  Coniferous fuels: {cf.get(True, 0):.1%} became large | other fuels: {cf.get(False, 0):.1%}")
    print("  Forest area (first letter of FIRE_NUMBER, FOREST_AREA):")
    area = dev.assign(forest_area=dev.FIRE_NUMBER.astype(str).str.strip().str[0])
    fa = area.groupby("forest_area").big.agg(["mean", "size"]).sort_values("mean", ascending=False, kind="stable")
    for k, r in fa.iterrows():
        print(f"    {k}: {int(r['size']):6,} fires, {r['mean']:.1%} became large")
    print("  (Latitude/longitude not used: the dictionary says coordinates are the final confirmed location, not necessarily the value at assessment; the forest area code exists at report time.)")
    print("→ These are all candidate terms for the formula. Choose the terms and weights of formula v1 from Q3 and Q4, and write down a reason for each.")
    print("  They are also the rates that the historical_rate whitelist (FIRE_TYPE, FUEL_TYPE, FOREST_AREA) looks up.")

    section("[Q5] Is the label reasonable? Were large fires left unfought?")
    nf = d[d.big == 1].FIRE_FIGHTING_START_DATE.isna().mean()
    print(f"Only {nf:.1%} of large fires have no firefighting start time → almost all large fires were actively fought, so the label is usable.")

    section("[Q6] Are large fires independent of each other? (same fire complex)")
    cx = d.FIRE_NAME.fillna("").str.contains("Complex", case=False)
    print(f"Large fires in a complex (name contains 'Complex'): {d[cx].big.sum()} of {d.big.sum()} large fires")
    top = d[(d.YEAR == LAST_YEAR) & (d.big == 1)].FIRE_NAME.fillna("(unnamed)").str.strip().value_counts().head(3)
    print(f"Fire complexes with the most large fires in {LAST_YEAR}:", top.to_dict())
    print("→ Fires in the same complex are related, so hits should also be reported once per complex.")

    section("[Q7] Baseline: how many large fires does 'largest first' catch in the top 40 each year?")
    rows = []
    for y, g in d[d.YEAR >= 2016].groupby("YEAR"):
        top40 = g.sort_values("ASSESSMENT_HECTARES", ascending=False, kind="stable").head(N_CREWS)
        rows.append((y, len(g), int(g.big.sum()), int(top40.big.sum())))
    print(f"{'Year':>6} {'Fires':>7} {'Large':>5} {'Top-40 hits':>11}")
    for y, n, b, h in rows:
        print(f"{y:>6} {n:>7,} {b:>5} {h:>11}")
    print(f"{len(rows)}-year total: {sum(r[3] for r in rows)} of {sum(r[2] for r in rows)} large fires caught")
    print("→ This is the number to beat. Ties are broken by original row order (teammates verifying independently must use the same rule).")


if __name__ == "__main__":
    main()
