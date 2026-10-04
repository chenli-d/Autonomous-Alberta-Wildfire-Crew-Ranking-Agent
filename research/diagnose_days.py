"""Diagnostic: on day-level crew allocation, which large fires does each ranking catch?

Phase 2, step 2. Trains the phase 1 RF, then on every test-year day with more than H newly
assessed fires ranks that day's fires with the RF ranking and the baseline ranking
(train_rf.py) and puts each large fire in one of four groups:

    both       - in the top H of both rankings
    rf_only    - in the top H of the RF ranking only
    base_only  - in the top H of the baseline ranking only
    neither    - in the top H of neither

It then prints, step by step, where the two rankings differ and what those fires look like.
FIRE_NAME (complex name) is shown for reading the results only; it is never a model input.

Usage (from the repo root):
    python research/diagnose_days.py
    python research/diagnose_days.py --train-start 2006 --train-end 2022 --test-year 2023
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "model"))
from train_rf import PROB_COL, RESERVED_YEAR, Preprocessor, baseline_ranking, load_data, rf_ranking  # noqa: E402

H = 10
CONIFER = {"C1", "C2", "C3", "C4", "C7"}  # coniferous fuel types (dictionary p.12-13)
SHOW_COLS = ["assessment_date", "fire_id", "FIRE_NAME", "day_fires", "rf_rank", "base_rank", PROB_COL,
             "ASSESSMENT_HECTARES", "FIRE_SPREAD_RATE", "RELATIVE_HUMIDITY", "WIND_SPEED",
             "FIRE_TYPE", "FUEL_TYPE", "CURRENT_SIZE"]


def section(title):
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def parse_args():
    p = argparse.ArgumentParser(description="Day-level allocation diagnostic")
    p.add_argument("--train-start", type=int, default=2006)
    p.add_argument("--train-end", type=int, default=2023)
    p.add_argument("--test-year", type=int, default=2024)
    args = p.parse_args()
    if args.train_end >= args.test_year:
        p.error("--train-end must be < --test-year")
    if args.test_year == RESERVED_YEAR:
        p.error(f"--test-year {RESERVED_YEAR} is reserved for the final run")
    return args


def train_and_score(df, args):
    """Step 0: train the phase 1 RF and score every fire of the test year."""
    train = df[(df["YEAR"] >= args.train_start) & (df["YEAR"] <= args.train_end)]
    test = df[df["YEAR"] == args.test_year].copy()
    prep = Preprocessor().fit(train)
    model = RandomForestClassifier(n_estimators=500, random_state=42, n_jobs=-1)
    model.fit(prep.transform(train), train["y"])
    test[PROB_COL] = model.predict_proba(prep.transform(test))[:, 1]
    return test


def rank_each_day(test):
    """Step 1: on each day with > H fires, give every fire its RF rank and baseline rank."""
    fires_per_day = test.groupby("assessment_date")["fire_id"].size()
    days = []
    for d in fires_per_day[fires_per_day > H].index:
        day = test[test["assessment_date"] == d]
        rf = rf_ranking(day)
        rf["rf_rank"] = range(1, len(rf) + 1)
        base = baseline_ranking(day)
        base["base_rank"] = range(1, len(base) + 1)
        merged = rf.merge(base[["fire_id", "base_rank"]], on="fire_id")
        merged["day_fires"] = len(day)
        days.append(merged)
    return pd.concat(days, ignore_index=True)


def group(row):
    in_rf, in_base = row["rf_rank"] <= H, row["base_rank"] <= H
    if in_rf and in_base:
        return "both"
    if in_rf:
        return "rf_only"
    if in_base:
        return "base_only"
    return "neither"


def main():
    args = parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)

    test = train_and_score(load_data(), args)
    fires = rank_each_day(test)
    fires["group"] = fires.apply(group, axis=1)
    large = fires[fires["y"] == 1]

    section(f"Setup: train {args.train_start}-{args.train_end}, test {args.test_year}, H = {H}")
    print(f"{fires['assessment_date'].nunique()} days with more than {H} fires, "
          f"{len(fires)} fires, {len(large)} large fires")

    section("Step 2: large fires by group")
    print(large["group"].value_counts().reindex(["both", "base_only", "rf_only", "neither"], fill_value=0).to_string())
    print(f"RF hits = both + rf_only = {int((large['group'].isin(['both', 'rf_only'])).sum())}; "
          f"baseline hits = both + base_only = {int((large['group'].isin(['both', 'base_only'])).sum())}")

    section("Step 3: on which days do the rankings differ?")
    diff = large[large["group"].isin(["rf_only", "base_only"])]
    if diff.empty:
        print("On every day both rankings catch the same large fires.")
    else:
        print(diff.groupby(["assessment_date", "group"]).size().unstack(fill_value=0).to_string())

    section("Step 4: the fires behind the differences, and the fires both missed")
    for g in ["base_only", "rf_only", "neither"]:
        rows = large[large["group"] == g].sort_values(["assessment_date", "rf_rank"])
        print(f"\n-- {g}: {len(rows)} fires --")
        if not rows.empty:
            print(rows[SHOW_COLS].round(3).to_string(index=False))

    section("Step 5: complexes among the large fires (FIRE_NAME, for reading only)")
    named = large.assign(complex=large["FIRE_NAME"].fillna("(no name)"))
    print(pd.crosstab(named["complex"], named["group"]).to_string())

    section("Step 6: do fire type and fuel separate the groups?")
    print(pd.crosstab(large["group"], large["FIRE_TYPE"]).to_string())
    print()
    print(pd.crosstab(large["group"], large["FUEL_TYPE"].isin(CONIFER).rename("conifer")).to_string())

    section("Step 7: medians by group (large fires)")
    print(large.groupby("group")[["ASSESSMENT_HECTARES", "FIRE_SPREAD_RATE", PROB_COL]].median().round(3).to_string())


if __name__ == "__main__":
    main()
