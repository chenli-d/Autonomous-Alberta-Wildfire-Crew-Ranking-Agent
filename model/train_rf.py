"""Baseline Random Forest for wildfire crew ranking.

Trains an RF on initial-assessment features to predict large fires (final area > 200 ha),
ranks test-year fires, allocates H crews on one assessment day, and compares the RF
ranking with a "largest first" baseline (ASSESSMENT_HECTARES).
"""

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "raw" / "fp-historical-wildfire-data-2006-2025.csv"
OUTPUT_ROOT = REPO_ROOT / "outputs"

RESERVED_YEAR = 2025
LARGE_FIRE_HA = 200

NUMERIC_FEATURES = [
    "ASSESSMENT_HECTARES",
    "FIRE_SPREAD_RATE",
    "TEMPERATURE",
    "RELATIVE_HUMIDITY",
    "WIND_SPEED",
]
CATEGORICAL_FEATURES = [
    "FIRE_TYPE",
    "FUEL_TYPE",
    "FIRE_POSITION_ON_SLOPE",
    "WEATHER_CONDITIONS_OVER_FIRE",
    "FOREST_AREA",
]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
PROB_COL = "rf_probability"


# ---------------------------------------------------------------- arguments


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Baseline RF for wildfire crew ranking")
    p.add_argument("--train-start", type=int, required=True)
    p.add_argument("--train-end", type=int, required=True)
    p.add_argument("--test-year", type=int, required=True)
    p.add_argument("--crews", type=int, default=10, help="Available crews H")
    p.add_argument("--allocation-date", required=True, help="YYYY-MM-DD inside the test year")
    p.add_argument("--run-name", required=True)
    p.add_argument("--final", action="store_true", help=f"Required iff --test-year {RESERVED_YEAR}")
    args = p.parse_args(argv)

    if args.train_start > args.train_end:
        p.error("--train-start must be <= --train-end")
    if args.train_end >= args.test_year:
        p.error("--train-end must be < --test-year")
    if args.crews < 1:
        p.error("--crews must be >= 1")
    try:
        args.allocation_date = date.fromisoformat(args.allocation_date)
    except ValueError:
        p.error("--allocation-date must be YYYY-MM-DD")
    if args.allocation_date.year != args.test_year:
        p.error("--allocation-date must be inside --test-year")
    if args.test_year == RESERVED_YEAR and not args.final:
        p.error(f"--test-year {RESERVED_YEAR} is reserved; pass --final to run it")
    if args.final and args.test_year != RESERVED_YEAR:
        p.error(f"--final is only allowed with --test-year {RESERVED_YEAR}")
    return args


# ---------------------------------------------------------------- data


def load_data():
    df = pd.read_csv(DATA_PATH, low_memory=False)
    fire_number = df["FIRE_NUMBER"].str.strip()
    df["fire_id"] = df["YEAR"].astype(str) + ":" + fire_number
    if df["fire_id"].duplicated().any():
        sys.exit("fire_id has duplicates")
    df["FOREST_AREA"] = fire_number.str[0]
    df["y"] = (df["CURRENT_SIZE"] > LARGE_FIRE_HA).astype(int)
    df["assessment_date"] = pd.to_datetime(df["ASSESSMENT_DATETIME"], errors="coerce").dt.date
    for col in CATEGORICAL_FEATURES:
        # Blank strings (e.g. "  ") are treated as missing.
        cleaned = df[col].astype("string").str.strip()
        df[col] = cleaned.mask(cleaned == "").fillna("Unknown").astype(str)
    return df


class Preprocessor:
    """Median imputation + one-hot encoding, fit on the training window only."""

    def fit(self, train):
        self.medians = train[NUMERIC_FEATURES].median()
        self.categories = {c: sorted(train[c].unique()) for c in CATEGORICAL_FEATURES}
        return self

    def transform(self, df):
        parts = [df[NUMERIC_FEATURES].fillna(self.medians)]
        for col, cats in self.categories.items():
            # Categories unseen in training get all zeros.
            onehot = pd.DataFrame(
                {f"{col}={cat}": (df[col] == cat).astype(int) for cat in cats}, index=df.index
            )
            parts.append(onehot)
        return pd.concat(parts, axis=1)


# ---------------------------------------------------------------- ranking & allocation


def _rank(df, keys, ascending):
    ordered = df.sort_values(keys, ascending=ascending, na_position="last", kind="mergesort")
    return ordered.reset_index(drop=True)


def rf_ranking(df):
    """RF prob desc -> ASSESSMENT_HECTARES desc -> FIRE_SPREAD_RATE desc -> fire_id asc."""
    keys = [PROB_COL, "ASSESSMENT_HECTARES", "FIRE_SPREAD_RATE", "fire_id"]
    return _rank(df, keys, [False, False, False, True])


def baseline_ranking(df):
    """ASSESSMENT_HECTARES desc -> FIRE_SPREAD_RATE desc -> fire_id asc."""
    keys = ["ASSESSMENT_HECTARES", "FIRE_SPREAD_RATE", "fire_id"]
    return _rank(df, keys, [False, False, True])


def allocate(ranking, H):
    """First min(H, n) fires keep a crew; the rest get none."""
    n = len(ranking)
    status = np.array(["no_crew"] * n, dtype=object)
    status[: min(H, n)] = "kept"
    return status


def apply_crew_cut(ranking, H):
    """Crews fall from H to floor(0.8 * H); ranks H_cut+1..min(H, n) are displaced."""
    n = len(ranking)
    H_cut = math.floor(0.8 * H)
    status = np.array(["no_crew"] * n, dtype=object)
    status[: min(H, n)] = "displaced"
    status[: min(H_cut, n)] = "kept"
    return status


# ---------------------------------------------------------------- reporting


def print_displaced_comparison(day_rf, status, H, H_cut):
    print("\n=== Displaced-fire Comparison (RF ranking) ===")
    displaced = day_rf[status == "displaced"]
    if displaced.empty:
        print("No fires displaced.")
        return
    last_kept = day_rf.iloc[H_cut - 1] if H_cut >= 1 else None

    for _, fire in displaced.iterrows():
        rank = int(fire["rank"])
        print(f"\nFire {fire['fire_id']}  rank #{rank}  probability {fire[PROB_COL]:.4f}")
        print(f"Old cutoff H = {H}, new cutoff H_cut = {H_cut}")
        print(
            f"Reason: ranked #{rank}; after crews fell from {H} to {H_cut}, "
            f"only ranks 1-{H_cut} keep a crew."
        )
        if last_kept is None:
            print("No fire keeps a crew after the cut.")
            for col in FEATURES:
                print(f"  {col:<30} {fire[col]}")
            continue
        table = pd.DataFrame(
            {
                f"displaced #{rank} ({fire['fire_id']})": [fire[PROB_COL]] + [fire[c] for c in FEATURES],
                f"last kept #{H_cut} ({last_kept['fire_id']})": [last_kept[PROB_COL]]
                + [last_kept[c] for c in FEATURES],
            },
            index=[PROB_COL] + FEATURES,
        )
        print(table.to_string())


# ---------------------------------------------------------------- main


def main(argv=None):
    args = parse_args(argv)
    H = args.crews
    H_cut = math.floor(0.8 * H)
    out_dir = OUTPUT_ROOT / args.run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_data()
    train = df[(df["YEAR"] >= args.train_start) & (df["YEAR"] <= args.train_end)].copy()
    test = df[df["YEAR"] == args.test_year].copy()

    prep = Preprocessor().fit(train)
    X_train, X_test = prep.transform(train), prep.transform(test)

    model = RandomForestClassifier(n_estimators=500, random_state=42, n_jobs=-1)
    model.fit(X_train, train["y"])
    test[PROB_COL] = model.predict_proba(X_test)[:, 1]

    # Test-year rankings (raw feature values are used for tie-breaks).
    rf_rank = rf_ranking(test)
    rf_rank.insert(0, "rank", np.arange(1, len(rf_rank) + 1))
    base_rank = baseline_ranking(test)
    base_rank["baseline_rank"] = np.arange(1, len(base_rank) + 1)
    rf_rank = rf_rank.merge(base_rank[["fire_id", "baseline_rank"]], on="fire_id", how="left")

    top_k = int(test["y"].sum())

    # Allocation day: re-rank only that day's fires, reusing RF probabilities.
    day = test[test["assessment_date"] == args.allocation_date]
    day_rf = rf_ranking(day)
    day_rf.insert(0, "rank", np.arange(1, len(day_rf) + 1))
    day_base = baseline_ranking(day)
    day_base["baseline_rank"] = np.arange(1, len(day_base) + 1)
    day_rf = day_rf.merge(day_base[["fire_id", "baseline_rank"]], on="fire_id", how="left")

    rf_alloc, rf_cut = allocate(day_rf, H), apply_crew_cut(day_rf, H)
    base_alloc, base_cut = allocate(day_base, H), apply_crew_cut(day_base, H)
    day_rf["status"] = rf_cut

    metrics = {
        "train_rows": len(train),
        "train_large": int(train["y"].sum()),
        "test_rows": len(test),
        "test_large": int(test["y"].sum()),
        "rf_roc_auc": float(roc_auc_score(test["y"], test[PROB_COL])),
        "rf_average_precision": float(average_precision_score(test["y"], test[PROB_COL])),
        "baseline_roc_auc": float(roc_auc_score(test["y"], test["ASSESSMENT_HECTARES"])),
        "top_k": top_k,
        "rf_top_k_large": int(rf_rank["y"].iloc[:top_k].sum()),
        "baseline_top_k_large": int(base_rank["y"].iloc[:top_k].sum()),
        "allocation_date": args.allocation_date.isoformat(),
        "allocation_fires": len(day),
        "allocation_large": int(day["y"].sum()),
        "H": H,
        "H_cut": H_cut,
        "rf_hits_at_H": int(day_rf["y"][rf_alloc == "kept"].sum()),
        "rf_hits_at_H_cut": int(day_rf["y"][rf_cut == "kept"].sum()),
        "baseline_hits_at_H": int(day_base["y"][base_alloc == "kept"].sum()),
        "baseline_hits_at_H_cut": int(day_base["y"][base_cut == "kept"].sum()),
    }

    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    out_cols = ["rank", "fire_id", PROB_COL, "baseline_rank"] + FEATURES
    rf_rank[out_cols + ["y"]].to_csv(out_dir / f"ranking_{args.test_year}.csv", index=False)
    (
        pd.DataFrame({"feature": X_train.columns, "importance": model.feature_importances_})
        .sort_values("importance", ascending=False)
        .to_csv(out_dir / "feature_importance.csv", index=False)
    )
    day_rf[out_cols + ["status", "y"]].to_csv(
        out_dir / f"allocation_{args.allocation_date.isoformat()}.csv", index=False
    )

    print("=== Metrics ===")
    print(json.dumps(metrics, indent=2))
    print_displaced_comparison(day_rf, rf_cut, H, H_cut)


if __name__ == "__main__":
    main()
