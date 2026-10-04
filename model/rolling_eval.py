"""Rolling-origin validation of the phase 1 RF on day-level crew allocation.

For each validation year Y in VALIDATION_YEARS, the RF is trained on 2006..Y-1 and
evaluated on Y. On every day of Y with more than H newly assessed fires, the day's fires
are ranked with the RF ranking and the baseline ranking (same rules as train_rf.py), and
large fires among the top H and top H_cut are counted, per fire (primary) and per fire
complex (secondary).
"""

import argparse
import json
import math

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

from train_rf import OUTPUT_ROOT, PROB_COL, Preprocessor, baseline_ranking, load_data, rf_ranking

VALIDATION_YEARS = list(range(2016, 2024))
FIRST_TRAIN_YEAR = 2006
H = 10
H_CUT = math.floor(0.8 * H)


def add_complex_id(df):
    """Group key for fire complexes: '<year>:<complex name>', else the fire's own id.

    FIRE_NAME holds the complex name, or 'fire name then complex name' (dictionary p.6).
    Used for evaluation only, never as a feature.
    """
    name = df["FIRE_NAME"].astype("string").str.strip()
    is_complex = name.str.endswith("Complex", na=False)
    complex_name = name.str.split(" Fire ").str[-1]
    df["complex_id"] = np.where(is_complex, df["YEAR"].astype(str) + ":" + complex_name.fillna(""), df["fire_id"])
    return df


def evaluate_year(test, ranking):
    """Day-level hits for one ranking function over one test year."""
    fires_per_day = test.groupby("assessment_date")["fire_id"].size()
    hits_H = hits_cut = large = days = 0
    large_complexes, picked_H, picked_cut = set(), set(), set()
    for d in fires_per_day[fires_per_day > H].index:
        day = test[test["assessment_date"] == d]
        ranked = ranking(day)
        top_H, top_cut = ranked.iloc[:H], ranked.iloc[:H_CUT]
        hits_H += int(top_H["y"].sum())
        hits_cut += int(top_cut["y"].sum())
        large += int(day["y"].sum())
        days += 1
        # A complex counts as caught if any of its large fires is picked on any day of the year.
        large_complexes |= set(day.loc[day["y"] == 1, "complex_id"])
        picked_H |= set(top_H.loc[top_H["y"] == 1, "complex_id"])
        picked_cut |= set(top_cut.loc[top_cut["y"] == 1, "complex_id"])
    return {
        "days": days,
        "large_fires": large,
        "hits_at_H": hits_H,
        "hits_at_H_cut": hits_cut,
        "large_complexes": len(large_complexes),
        "complex_hits_at_H": len(picked_H),
        "complex_hits_at_H_cut": len(picked_cut),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Rolling-origin validation of the phase 1 RF")
    p.add_argument("--run-name", required=True)
    args = p.parse_args(argv)
    out_dir = OUTPUT_ROOT / args.run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    df = add_complex_id(load_data())
    rows = []
    for year in VALIDATION_YEARS:
        train = df[(df["YEAR"] >= FIRST_TRAIN_YEAR) & (df["YEAR"] < year)]
        test = df[df["YEAR"] == year].copy()

        prep = Preprocessor().fit(train)
        model = RandomForestClassifier(n_estimators=500, random_state=42, n_jobs=-1)
        model.fit(prep.transform(train), train["y"])
        test[PROB_COL] = model.predict_proba(prep.transform(test))[:, 1]

        rows.append({"year": year, "ranking": "baseline", **evaluate_year(test, baseline_ranking),
                     "roc_auc": float(roc_auc_score(test["y"], test["ASSESSMENT_HECTARES"])),
                     "average_precision": None})
        rows.append({"year": year, "ranking": "rf", **evaluate_year(test, rf_ranking),
                     "roc_auc": float(roc_auc_score(test["y"], test[PROB_COL])),
                     "average_precision": float(average_precision_score(test["y"], test[PROB_COL]))})
        print(f"{year} done", flush=True)

    per_year = pd.DataFrame(rows)
    per_year.to_csv(out_dir / "rolling_per_year.csv", index=False)
    sum_cols = ["days", "large_fires", "hits_at_H", "hits_at_H_cut",
                "large_complexes", "complex_hits_at_H", "complex_hits_at_H_cut"]
    totals = per_year.groupby("ranking", sort=False)[sum_cols].sum()
    (out_dir / "rolling_summary.json").write_text(json.dumps(totals.to_dict(orient="index"), indent=2))
    pd.set_option("display.width", 250)
    print(per_year.round(3).to_string(index=False))
    print("\n=== Totals 2016-2023 ===")
    print(totals.to_string())


if __name__ == "__main__":
    main()
