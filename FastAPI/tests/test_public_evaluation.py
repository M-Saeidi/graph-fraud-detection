"""Synthetic tests for fair A0/B1/C1 comparison and business capture metrics."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

import public_evaluation as evaluation


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_synthetic_dataset(directory: Path, row_count: int = 1000) -> Path:
    directory.mkdir()
    start = datetime(2019, 1, 1)
    transaction_rows = []
    labels = {}
    for index in range(row_count):
        transaction_rows.append({
            "id": index + 1,
            "date": (start + timedelta(days=index)).strftime("%Y-%m-%d %H:%M:%S"),
            "client_id": 1,
            "card_id": 10,
            "merchant_id": 20 + index % 4,
            "amount": f"${10 + index % 90}.00",
            "errors": "Insufficient Balance,Technical Glitch" if index == 0 else "",
        })
        labels[str(index + 1)] = "Yes" if index % 25 == 0 else "No"
    write_csv(directory / "transactions_data.csv", transaction_rows)
    write_csv(directory / "users_data.csv", [{
        "id": 1, "current_age": 35, "credit_score": 650, "yearly_income": "$60000",
    }])
    write_csv(directory / "cards_data.csv", [{
        "id": 10, "client_id": 1, "credit_limit": "$5000",
    }])
    (directory / "train_fraud_labels.json").write_text(
        json.dumps({"target": labels}), encoding="utf-8",
    )
    return directory


def test_average_precision_groups_tied_scores():
    labels = np.asarray([True, False, True, False])
    scores = np.asarray([0.9, 0.9, 0.1, 0.1])
    assert evaluation.average_precision(labels, scores) == pytest.approx(0.5)


def test_business_capture_uses_fixed_capacity_and_positive_amounts():
    labels = np.asarray([True, False, True, False])
    scores = np.asarray([0.9, 0.8, 0.2, 0.1])
    amounts = np.asarray([100.0, 1000.0, -50.0, 20.0])
    result = evaluation.business_capture_metrics(
        labels, scores, amounts, capacities=(0.5,),
    )[0]
    assert result["reviewed_transactions"] == 2
    assert result["fraud_captured"] == 1
    assert result["fraud_capture_pct"] == 50.0
    assert result["fraud_amount_captured_source_units"] == 100.0
    assert result["fraud_value_capture_pct"] == 100.0


def test_full_public_evaluation_uses_one_chronological_split_for_all_stages(tmp_path, monkeypatch):
    source = write_synthetic_dataset(tmp_path / "kaggle-v1")
    monkeypatch.setattr(evaluation, "__file__", str(tmp_path / "FastAPI" / "public_evaluation.py"))

    result = evaluation.run_evaluation(input_dir=source, output_name="synthetic-evaluation")

    assert result["status"] == "exploratory_provenance_unverified"
    assert result["publication_clearance"] is False
    assert result["counts"]["transaction_rows"] == 1000
    assert result["counts"]["label_rows"] == 1000
    assert result["counts"]["test_rows"] == 200
    assert result["metrics"]["A0"]["feature_count"] == 5
    assert result["metrics"]["AB"]["feature_count"] == 9
    assert result["metrics"]["ABC"]["feature_count"] == 15
    assert all(0.0 <= result["metrics"][stage]["auprc_average_precision"] <= 1.0 for stage in ("A0", "AB", "ABC"))
    output = tmp_path / "local-data" / "synthetic-evaluation"
    assert (output / "evaluation.json").is_file()
    assert all((output / "models" / f"{stage.lower()}.json").is_file() for stage in ("A0", "AB", "ABC"))
    assert not (output / "labels.csv").exists()
    with pytest.raises(FileExistsError):
        evaluation.run_evaluation(input_dir=source, output_name="synthetic-evaluation")
