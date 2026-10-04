"""Run the existing model and load only freshly generated, sanitized results."""
import csv
import subprocess
import sys
from pathlib import Path

from app.ranking_service import load_rankings
from app.review_service import load_allocation_context

RUN_NAME = "ui_demo"


def run_assessment(root, train_start, train_end, test_year, assessment_date, crews):
    if not (2006 <= train_start <= train_end <= 2023 and train_end < test_year <= 2024):
        raise ValueError("Choose training years from 2006–2023 with start ≤ end < test year (through 2024).")
    if assessment_date.year != test_year:
        raise ValueError("Assessment date must be within the selected test year.")
    if crews < 1:
        raise ValueError("Available crews must be at least 1.")
    root = Path(root).resolve()
    output = root / "outputs" / RUN_NAME
    allocation = output / f"allocation_{assessment_date.isoformat()}.csv"
    metadata = output / "metrics.json"
    annual = output / f"ranking_{test_year}.csv"
    # Remove this run's inputs before execution so no stage can reuse stale output.
    for path in (allocation, metadata, annual):
        path.unlink(missing_ok=True)
    subprocess.run([sys.executable, str(root / "model" / "train_rf.py"),
                    "--train-start", str(train_start), "--train-end", str(train_end),
                    "--test-year", str(test_year), "--crews", str(crews),
                    "--allocation-date", assessment_date.isoformat(), "--run-name", RUN_NAME],
                   cwd=root, capture_output=True, text=True, check=True)
    with allocation.open(newline="", encoding="utf-8-sig") as file:
        if not {"fire_id", "rank", "rf_probability", "baseline_rank", "status"}.issubset(csv.DictReader(file).fieldnames or []):
            raise ValueError("Generated allocation CSV is missing required ranking columns.")
    official = root / "data/raw/fp-historical-wildfire-data-2006-2025.csv"
    records, diagnostics = load_rankings(allocation, official, assessment_date)
    # Review context is optional: its failure must not hide a successful RF assessment.
    review_error = None
    context, annual_ranks = None, {}
    try:
        context = load_allocation_context(allocation, metadata, assessment_date)
        annual_records, _ = load_rankings(annual, official, assessment_date)
        annual_ranks = {row["fire_id"]: row["rank"] for row in annual_records}
        if set(annual_ranks) != {row["fire_id"] for row in records}:
            raise ValueError("Annual ranking and daily allocation IDs do not match.")
        context["source_versions"] = [path.stat().st_mtime_ns for path in (allocation, metadata, annual, official)]
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as error:
        review_error = str(error)
    return {"records": records, "diagnostics": diagnostics, "context": context,
            "annual_ranks": annual_ranks, "review_error": review_error,
            "settings": {"train_start": train_start, "train_end": train_end, "test_year": test_year,
                         "assessment_date": assessment_date, "crews": crews}}
