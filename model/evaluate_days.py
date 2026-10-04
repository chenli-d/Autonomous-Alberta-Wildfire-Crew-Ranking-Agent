"""Multi-day allocation evaluation for the RF and "largest first" rankings.

Trains the same RF as train_rf.py, then evaluates crew allocation on many test-year days:
- "own" day sets: for each H, every assessment day with more than H newly assessed fires.
  H = 10 is the primary result; 5, 15 and 20 are sensitivity checks.
- "common" day set: every H on the same days (more than max(H_VALUES) fires). Diagnostic
  only: it separates the effect of H from the effect of which days are included.
On each day, both rankings follow train_rf.py; large fires are counted among the top H
and the top H_cut = floor(0.8 * H).
"""

import argparse
import json
import math

import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from train_rf import (
    OUTPUT_ROOT,
    PROB_COL,
    RESERVED_YEAR,
    Preprocessor,
    baseline_ranking,
    load_data,
    rf_ranking,
)

H_VALUES = [5, 10, 15, 20]
PRIMARY_H = 10


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Multi-day allocation evaluation")
    p.add_argument("--train-start", type=int, required=True)
    p.add_argument("--train-end", type=int, required=True)
    p.add_argument("--test-year", type=int, required=True)
    p.add_argument("--run-name", required=True)
    p.add_argument("--final", action="store_true", help=f"Required iff --test-year {RESERVED_YEAR}")
    args = p.parse_args(argv)

    if args.train_start > args.train_end:
        p.error("--train-start must be <= --train-end")
    if args.train_end >= args.test_year:
        p.error("--train-end must be < --test-year")
    if args.test_year == RESERVED_YEAR and not args.final:
        p.error(f"--test-year {RESERVED_YEAR} is reserved; pass --final to run it")
    if args.final and args.test_year != RESERVED_YEAR:
        p.error(f"--final is only allowed with --test-year {RESERVED_YEAR}")
    return args


def day_hits(day, H, H_cut):
    """Large fires among the top H and top H_cut of each ranking on one day."""
    rf = rf_ranking(day)
    base = baseline_ranking(day)
    return {
        "rf_hits_at_H": int(rf["y"].iloc[:H].sum()),
        "baseline_hits_at_H": int(base["y"].iloc[:H].sum()),
        "rf_hits_at_H_cut": int(rf["y"].iloc[:H_cut].sum()),
        "baseline_hits_at_H_cut": int(base["y"].iloc[:H_cut].sum()),
    }


def win_loss(days, level):
    """Totals and days RF wins / loses / ties at one cutoff ("H" or "H_cut")."""
    diff = days[f"rf_hits_at_{level}"] - days[f"baseline_hits_at_{level}"]
    return {
        "rf_total": int(days[f"rf_hits_at_{level}"].sum()),
        "baseline_total": int(days[f"baseline_hits_at_{level}"].sum()),
        "rf_wins": int((diff > 0).sum()),
        "rf_losses": int((diff < 0).sum()),
        "ties": int((diff == 0).sum()),
        "ties_with_large": int(((diff == 0) & (days["large"] > 0)).sum()),
    }


def summarize(days):
    return {
        "days": len(days),
        "days_with_large": int((days["large"] > 0).sum()),
        "large_fires": int(days["large"].sum()),
        "at_H": win_loss(days, "H"),
        "at_H_cut": win_loss(days, "H_cut"),
    }


def main(argv=None):
    args = parse_args(argv)
    out_dir = OUTPUT_ROOT / args.run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_data()
    train = df[(df["YEAR"] >= args.train_start) & (df["YEAR"] <= args.train_end)].copy()
    test = df[df["YEAR"] == args.test_year].copy()

    prep = Preprocessor().fit(train)
    model = RandomForestClassifier(n_estimators=500, random_state=42, n_jobs=-1)
    model.fit(prep.transform(train), train["y"])
    test[PROB_COL] = model.predict_proba(prep.transform(test))[:, 1]

    fires_per_day = test.groupby("assessment_date")["fire_id"].size()
    day_sets = {
        "own": {H: fires_per_day[fires_per_day > H].index for H in H_VALUES},
        "common": {H: fires_per_day[fires_per_day > max(H_VALUES)].index for H in H_VALUES},
    }

    rows = []
    for day_set, dates_by_H in day_sets.items():
        for H, dates in dates_by_H.items():
            H_cut = math.floor(0.8 * H)
            for d in dates:
                day = test[test["assessment_date"] == d]
                rows.append(
                    {"day_set": day_set, "H": H, "H_cut": H_cut, "date": d.isoformat(),
                     "fires": len(day), "large": int(day["y"].sum()), **day_hits(day, H, H_cut)}
                )
    per_day = pd.DataFrame(rows)

    summary = {
        "train_rows": len(train),
        "train_large": int(train["y"].sum()),
        "test_rows": len(test),
        "test_large": int(test["y"].sum()),
        "primary_H": PRIMARY_H,
        "common_day_rule": f"more than {max(H_VALUES)} fires",
    }
    for day_set in day_sets:
        summary[day_set] = {
            str(H): {"H_cut": math.floor(0.8 * H), **summarize(group)}
            for H, group in per_day[per_day["day_set"] == day_set].groupby("H")
        }

    per_day.to_csv(out_dir / f"multiday_{args.test_year}.csv", index=False)
    (out_dir / "multiday_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
