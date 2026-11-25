"""Reproducibly compare A0, A+B, and A+B+C on caller-provided Kaggle-shaped data.

This evaluation trains three fresh native models under one chronological split.
It does not compare the existing RapidMiner-exported C1 model as if it were
trained under the same protocol.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import duckdb
import ijson
import numpy as np
import xgboost as xgb

from feature_assembler import C1_FEATURE_ORDER


DATASET_URL = "https://www.kaggle.com/datasets/computingvictor/transactions-fraud-datasets"
DATASET_VERSION_REFERENCE = 1
NEGATIVE_PER_POSITIVE = 20
CHRONOLOGICAL_TRAIN_FRACTION = 0.8
RANDOM_SEED = 949776430
BOOSTED_ROUNDS = 150
REVIEW_CAPACITIES = (0.001, 0.005, 0.01)
MAX_INPUT_BYTES = 2_000_000_000

INPUT_FILES = (
    "transactions_data.csv",
    "users_data.csv",
    "cards_data.csv",
    "train_fraud_labels.json",
)
REQUIRED_HEADERS = {
    "transactions_data.csv": {"id", "date", "client_id", "card_id", "merchant_id", "amount"},
    "users_data.csv": {"id", "current_age", "credit_score", "yearly_income"},
    "cards_data.csv": {"id", "client_id", "credit_limit"},
}
A0_FEATURES = ("amount", "yearlyIncome", "creditLimit", "currentAge", "creditScore")
B1_FEATURES = (
    "card_prior_txn_count",
    "card_prior_avg_amount",
    "amount_vs_card_avg",
    "time_since_prev_card_txn",
)
FEATURE_STAGES = {
    "A0": A0_FEATURES,
    "AB": A0_FEATURES + B1_FEATURES,
    "ABC": tuple(C1_FEATURE_ORDER),
}

XGBOOST_PARAMETERS = {
    "objective": "binary:logistic",
    "eval_metric": "aucpr",
    "booster": "gbtree",
    "tree_method": "hist",
    "max_depth": 6,
    "learning_rate": 0.1,
    "min_child_weight": 1.0,
    "subsample": 1.0,
    "colsample_bytree": 1.0,
    "lambda": 1.0,
    "alpha": 0.0,
    "seed": RANDOM_SEED,
    "nthread": 1,
}


def average_precision(labels: np.ndarray, scores: np.ndarray) -> float:
    """Compute step-wise average precision, grouping equal-score thresholds."""
    labels = np.asarray(labels, dtype=np.bool_)
    scores = np.asarray(scores, dtype=np.float64)
    if labels.ndim != 1 or scores.ndim != 1 or labels.shape != scores.shape or labels.size == 0:
        raise ValueError("labels and scores must be non-empty one-dimensional arrays of equal length.")
    if not np.isfinite(scores).all() or ((scores < 0.0) | (scores > 1.0)).any():
        raise ValueError("scores must be finite probabilities between zero and one.")
    positives = int(labels.sum())
    if positives == 0:
        raise ValueError("average precision requires at least one positive label.")

    order = np.argsort(-scores, kind="stable")
    sorted_scores = scores[order]
    sorted_labels = labels[order].astype(np.int64)
    threshold_ends = np.flatnonzero(
        np.concatenate((sorted_scores[1:] != sorted_scores[:-1], np.array([True])))
    )
    true_positives = np.cumsum(sorted_labels)[threshold_ends]
    precision = true_positives / (threshold_ends + 1)
    recall = true_positives / positives
    previous_recall = np.concatenate((np.array([0.0]), recall[:-1]))
    return float(np.sum((recall - previous_recall) * precision))


def business_capture_metrics(
    labels: np.ndarray,
    scores: np.ndarray,
    amounts: np.ndarray,
    *,
    capacities: tuple[float, ...] = REVIEW_CAPACITIES,
) -> list[dict[str, int | float]]:
    """Report fraud count/value captured at fixed ranked review capacities.

    Fraud amount is the sum of positive source amount values for true-fraud
    transactions in the reviewed queue. Currency is not inferred by this helper.
    """
    labels = np.asarray(labels, dtype=np.bool_)
    scores = np.asarray(scores, dtype=np.float64)
    amounts = np.asarray(amounts, dtype=np.float64)
    if labels.ndim != 1 or scores.shape != labels.shape or amounts.shape != labels.shape or labels.size == 0:
        raise ValueError("labels, scores, and amounts must be equal-length one-dimensional arrays.")
    if not np.isfinite(scores).all() or ((scores < 0.0) | (scores > 1.0)).any():
        raise ValueError("scores must be finite probabilities between zero and one.")
    if not np.isfinite(amounts).all():
        raise ValueError("amounts must be finite.")
    if not labels.any():
        raise ValueError("business capture requires at least one fraud-positive test row.")
    if not capacities or any(not 0.0 < capacity <= 1.0 for capacity in capacities):
        raise ValueError("review capacities must be between zero and one.")

    order = np.argsort(-scores, kind="stable")
    positive_amounts = np.clip(amounts, 0.0, None)
    total_fraud_value = float(positive_amounts[labels].sum())
    prevalence = float(labels.mean())
    results = []
    for capacity in capacities:
        reviewed_count = max(1, math.ceil(labels.size * capacity))
        reviewed = order[:reviewed_count]
        fraud_mask = labels[reviewed]
        captured_count = int(fraud_mask.sum())
        captured_value = float(positive_amounts[reviewed][fraud_mask].sum())
        precision = captured_count / reviewed_count
        expected_random = reviewed_count * prevalence
        results.append({
            "review_capacity_pct": capacity * 100.0,
            "reviewed_transactions": reviewed_count,
            "fraud_captured": captured_count,
            "fraud_capture_pct": 100.0 * captured_count / int(labels.sum()),
            "precision_pct": 100.0 * precision,
            "lift_vs_random": precision / prevalence if prevalence else 0.0,
            "fraud_amount_captured_source_units": captured_value,
            "fraud_value_capture_pct": 100.0 * captured_value / total_fraud_value if total_fraud_value else 0.0,
            "random_expected_fraud_count": expected_random,
        })
    return results


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _headers(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        header = next(csv.reader(stream), None)
    if not header or len(header) != len(set(header)):
        raise ValueError(f"Missing or duplicate CSV headers in {path.name}.")
    return set(header)


def _stream_labels(source: Path, destination: Path) -> dict[str, int]:
    counts = {"labeled": 0, "fraud": 0, "non_fraud": 0}
    with source.open("rb") as source_stream, destination.open("w", encoding="utf-8", newline="") as output_stream:
        writer = csv.writer(output_stream, lineterminator="\n")
        writer.writerow(("transaction_id", "is_fraud"))
        for transaction_id, label in ijson.kvitems(source_stream, "target"):
            if not isinstance(transaction_id, str) or re.fullmatch(r"[0-9]+", transaction_id) is None:
                raise ValueError("Label mapping contains a non-canonical transaction ID.")
            if label not in {"Yes", "No"}:
                raise ValueError("Label mapping values must be exactly Yes or No.")
            is_fraud = label == "Yes"
            writer.writerow((transaction_id, "true" if is_fraud else "false"))
            counts["labeled"] += 1
            counts["fraud" if is_fraud else "non_fraud"] += 1
    return counts


def _scalar(connection: duckdb.DuckDBPyConnection, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def _validate_unique(connection: duckdb.DuckDBPyConnection, table: str, column: str) -> None:
    duplicates = _scalar(
        connection,
        f"SELECT COUNT(*) FROM (SELECT {column} FROM {table} GROUP BY {column} HAVING COUNT(*) > 1)",
    )
    if duplicates:
        raise ValueError(f"{table} contains duplicate canonical {column} values.")


def _materialize_tables(
    connection: duckdb.DuckDBPyConnection,
    input_dir: Path,
    labels_csv: Path,
) -> dict[str, int]:
    for filename, required in REQUIRED_HEADERS.items():
        missing = required - _headers(input_dir / filename)
        if missing:
            raise ValueError(f"{filename} is missing required columns.")

    connection.execute("""
        CREATE TEMP TABLE transactions AS
        SELECT
            TRY_CAST(id AS BIGINT) AS transaction_id,
            TRY_STRPTIME(date, '%Y-%m-%d %H:%M:%S') AS event_time,
            TRY_CAST(client_id AS BIGINT) AS client_id,
            TRY_CAST(card_id AS BIGINT) AS card_id,
            TRY_CAST(merchant_id AS BIGINT) AS merchant_id,
            TRY_CAST(REGEXP_REPLACE(amount, '[^0-9.-]', '', 'g') AS DOUBLE) AS amount
        FROM read_csv(?, header=true, all_varchar=true, delim=',', quote='"', escape='"')
    """, [str(input_dir / "transactions_data.csv")])
    if _scalar(connection, "SELECT COUNT(*) FROM transactions WHERE transaction_id IS NULL"):
        raise ValueError("Transaction CSV contains invalid transaction IDs.")
    _validate_unique(connection, "transactions", "transaction_id")

    connection.execute(
        "CREATE TEMP TABLE labels AS "
        "SELECT TRY_CAST(transaction_id AS BIGINT) AS transaction_id, "
        "TRY_CAST(is_fraud AS BOOLEAN) AS is_fraud "
        "FROM read_csv(?, header=true, all_varchar=true, delim=',', quote='\"', escape='\"')",
        [str(labels_csv)],
    )
    if _scalar(connection, "SELECT COUNT(*) FROM labels WHERE transaction_id IS NULL OR is_fraud IS NULL"):
        raise ValueError("Label mapping contains invalid IDs or values.")
    _validate_unique(connection, "labels", "transaction_id")

    connection.execute("""
        CREATE TEMP TABLE users AS
        SELECT
            TRY_CAST(id AS BIGINT) AS client_id,
            TRY_CAST(current_age AS INTEGER) AS currentAge,
            TRY_CAST(credit_score AS INTEGER) AS creditScore,
            TRY_CAST(REGEXP_REPLACE(yearly_income, '[^0-9.-]', '', 'g') AS DOUBLE) AS yearlyIncome
        FROM read_csv(?, header=true, all_varchar=true, delim=',', quote='"', escape='"')
    """, [str(input_dir / "users_data.csv")])
    connection.execute("""
        CREATE TEMP TABLE cards AS
        SELECT
            TRY_CAST(id AS BIGINT) AS card_id,
            TRY_CAST(REGEXP_REPLACE(credit_limit, '[^0-9.-]', '', 'g') AS DOUBLE) AS creditLimit
        FROM read_csv(?, header=true, all_varchar=true, delim=',', quote='"', escape='"')
    """, [str(input_dir / "cards_data.csv")])
    _validate_unique(connection, "users", "client_id")
    _validate_unique(connection, "cards", "card_id")

    connection.execute("""
        CREATE TEMP TABLE labeled_history AS
        SELECT t.*, l.is_fraud
        FROM transactions AS t
        INNER JOIN labels AS l USING (transaction_id)
        WHERE t.event_time IS NOT NULL
    """)

    connection.execute("""
        CREATE TEMP TABLE windowed AS
        SELECT
            *,
            COUNT(*) FILTER (WHERE amount IS NOT NULL) OVER (
                PARTITION BY card_id ORDER BY EPOCH(event_time)
                RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS card_prior_count,
            AVG(amount) FILTER (WHERE amount IS NOT NULL) OVER (
                PARTITION BY card_id ORDER BY EPOCH(event_time)
                RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS card_prior_avg_amount,
            MAX(CASE WHEN amount IS NOT NULL THEN EPOCH(event_time) END) OVER (
                PARTITION BY card_id ORDER BY EPOCH(event_time)
                RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS card_previous_time,
            COUNT(*) OVER (
                PARTITION BY merchant_id ORDER BY EPOCH(event_time)
                RANGE BETWEEN UNBOUNDED PRECEDING AND 604800 PRECEDING
            ) AS merchant_prior_txn_count,
            COUNT(*) FILTER (WHERE is_fraud) OVER (
                PARTITION BY merchant_id ORDER BY EPOCH(event_time)
                RANGE BETWEEN UNBOUNDED PRECEDING AND 604800 PRECEDING
            ) AS merchant_prior_fraud_count,
            COUNT(DISTINCT card_id) OVER (
                PARTITION BY merchant_id ORDER BY EPOCH(event_time)
                RANGE BETWEEN UNBOUNDED PRECEDING AND 604800 PRECEDING
            ) AS merchant_prior_unique_cards,
            COUNT(DISTINCT card_id) FILTER (WHERE is_fraud) OVER (
                PARTITION BY merchant_id ORDER BY EPOCH(event_time)
                RANGE BETWEEN UNBOUNDED PRECEDING AND 604800 PRECEDING
            ) AS merchant_prior_unique_fraud_cards
        FROM labeled_history
    """)

    connection.execute("""
        CREATE TEMP TABLE model_rows AS
        SELECT
            w.transaction_id,
            w.event_time,
            w.is_fraud,
            w.amount,
            u.yearlyIncome,
            c.creditLimit,
            u.currentAge,
            u.creditScore,
            COALESCE(w.card_prior_count, 0)::BIGINT AS card_prior_txn_count,
            COALESCE(w.card_prior_avg_amount, 0.0)::DOUBLE AS card_prior_avg_amount,
            CASE
                WHEN COALESCE(w.card_prior_avg_amount, 0.0) = 0.0 THEN 0.0
                ELSE w.amount / w.card_prior_avg_amount
            END AS amount_vs_card_avg,
            CASE
                WHEN w.card_previous_time IS NULL THEN 0.0
                ELSE (EPOCH(w.event_time) - w.card_previous_time) / 3600.0
            END AS time_since_prev_card_txn,
            CASE WHEN w.merchant_id IS NULL THEN 0 ELSE COALESCE(w.merchant_prior_txn_count, 0) END::BIGINT AS merchant_prior_txn_count,
            CASE WHEN w.merchant_id IS NULL THEN 0 ELSE COALESCE(w.merchant_prior_fraud_count, 0) END::BIGINT AS merchant_prior_fraud_count,
            CASE
                WHEN w.merchant_id IS NULL OR COALESCE(w.merchant_prior_txn_count, 0) = 0 THEN 0.0
                ELSE 100.0 * w.merchant_prior_fraud_count / w.merchant_prior_txn_count
            END AS merchant_prior_fraud_rate_pct,
            CASE WHEN w.merchant_id IS NULL THEN 0 ELSE COALESCE(w.merchant_prior_unique_cards, 0) END::BIGINT AS merchant_prior_unique_cards,
            CASE WHEN w.merchant_id IS NULL THEN 0 ELSE COALESCE(w.merchant_prior_unique_fraud_cards, 0) END::BIGINT AS merchant_prior_unique_fraud_cards,
            CASE
                WHEN w.merchant_id IS NULL OR COALESCE(w.merchant_prior_unique_cards, 0) = 0 THEN 0.0
                ELSE 100.0 * w.merchant_prior_unique_fraud_cards / w.merchant_prior_unique_cards
            END AS merchant_prior_fraud_card_ratio_pct
        FROM windowed AS w
        INNER JOIN users AS u USING (client_id)
        INNER JOIN cards AS c USING (card_id)
        WHERE w.amount IS NOT NULL
          AND u.currentAge IS NOT NULL
          AND u.creditScore IS NOT NULL
          AND u.yearlyIncome IS NOT NULL
          AND c.creditLimit IS NOT NULL
          AND ISFINITE(w.amount)
          AND ISFINITE(u.yearlyIncome)
          AND ISFINITE(c.creditLimit)
    """)
    return {
        "transaction_rows": _scalar(connection, "SELECT COUNT(*) FROM transactions"),
        "label_rows": _scalar(connection, "SELECT COUNT(*) FROM labels"),
        "matched_labeled_rows": _scalar(connection, "SELECT COUNT(*) FROM labeled_history"),
        "modelable_labeled_rows": _scalar(connection, "SELECT COUNT(*) FROM model_rows"),
    }


def _create_split_and_sample(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    connection.execute("""
        CREATE TEMP TABLE ordered_rows AS
        SELECT *,
            ROW_NUMBER() OVER (ORDER BY event_time, transaction_id) AS temporal_index,
            COUNT(*) OVER () AS total_rows
        FROM model_rows
    """)
    connection.execute(f"""
        CREATE TEMP TABLE split_rows AS
        SELECT *, temporal_index <= FLOOR(total_rows * {CHRONOLOGICAL_TRAIN_FRACTION}) AS is_train
        FROM ordered_rows
    """)
    train_count = _scalar(connection, "SELECT COUNT(*) FROM split_rows WHERE is_train")
    test_count = _scalar(connection, "SELECT COUNT(*) FROM split_rows WHERE NOT is_train")
    train_fraud = _scalar(connection, "SELECT COUNT(*) FROM split_rows WHERE is_train AND is_fraud")
    test_fraud = _scalar(connection, "SELECT COUNT(*) FROM split_rows WHERE NOT is_train AND is_fraud")
    if train_count == 0 or test_count == 0 or train_fraud == 0 or test_fraud == 0:
        raise ValueError("The chronological split must contain fraud-positive rows in both train and test sets.")

    connection.execute(f"""
        CREATE TEMP TABLE sampled_train AS
        WITH train_rows AS (
            SELECT * FROM split_rows WHERE is_train
        ),
        positive_count AS (
            SELECT COUNT(*) AS n FROM train_rows WHERE is_fraud
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY is_fraud ORDER BY HASH(transaction_id), transaction_id
            ) AS sample_rank
            FROM train_rows
        )
        SELECT ranked.*
        FROM ranked CROSS JOIN positive_count
        WHERE ranked.is_fraud OR ranked.sample_rank <= positive_count.n * {NEGATIVE_PER_POSITIVE}
    """)
    sampled_rows = _scalar(connection, "SELECT COUNT(*) FROM sampled_train")
    sampled_fraud = _scalar(connection, "SELECT COUNT(*) FROM sampled_train WHERE is_fraud")
    sampled_non_fraud = sampled_rows - sampled_fraud
    return {
        "train_rows_before_downsampling": train_count,
        "train_rows_after_downsampling": sampled_rows,
        "train_fraud_rows": sampled_fraud,
        "train_non_fraud_rows": sampled_non_fraud,
        "test_rows": test_count,
        "test_fraud_rows": test_fraud,
    }


def _feature_matrix(connection: duckdb.DuckDBPyConnection, table: str, features: tuple[str, ...], *, include_amount: bool = False):
    columns = ", ".join(f'"{feature}"' for feature in features)
    extra = ", amount" if include_amount else ""
    data = connection.execute(
        f"SELECT {columns}, is_fraud{extra} FROM {table} ORDER BY event_time, transaction_id"
    ).fetchnumpy()
    matrix = np.column_stack([data[feature] for feature in features]).astype(np.float32, copy=False)
    labels = np.asarray(data["is_fraud"], dtype=np.bool_)
    amounts = np.asarray(data["amount"], dtype=np.float64) if include_amount else None
    if not np.isfinite(matrix).all():
        raise ValueError(f"Non-finite model feature in {table}.")
    return matrix, labels, amounts


def _average_precision(labels: np.ndarray, scores: np.ndarray) -> float:
    order = np.argsort(-scores, kind="stable")
    sorted_scores = scores[order]
    sorted_labels = labels[order].astype(np.int64)
    positives = int(sorted_labels.sum())
    if positives == 0:
        raise ValueError("AUPRC requires at least one fraud-positive test row.")
    ends = np.flatnonzero(np.concatenate((sorted_scores[1:] != sorted_scores[:-1], np.array([True]))))
    true_positives = np.cumsum(sorted_labels)[ends]
    precision = true_positives / (ends + 1)
    recall = true_positives / positives
    previous_recall = np.concatenate((np.array([0.0]), recall[:-1]))
    return float(np.sum((recall - previous_recall) * precision))


def _capture_metrics(labels: np.ndarray, scores: np.ndarray, amounts: np.ndarray) -> list[dict[str, Any]]:
    order = np.argsort(-scores, kind="stable")
    positive_amounts = np.clip(amounts, 0.0, None)
    total_fraud_count = int(labels.sum())
    total_fraud_amount = float(positive_amounts[labels].sum())
    prevalence = float(labels.mean())
    output = []
    for capacity in REVIEW_CAPACITIES:
        reviewed_count = max(1, math.ceil(len(labels) * capacity))
        reviewed = order[:reviewed_count]
        fraud_mask = labels[reviewed]
        captured_count = int(fraud_mask.sum())
        captured_amount = float(positive_amounts[reviewed][fraud_mask].sum())
        precision = captured_count / reviewed_count
        output.append({
            "review_capacity_pct": capacity * 100,
            "reviewed_transactions": reviewed_count,
            "fraud_captured": captured_count,
            "fraud_capture_pct": 100 * captured_count / total_fraud_count,
            "precision_pct": 100 * precision,
            "lift_vs_random": precision / prevalence if prevalence else 0.0,
            "fraud_amount_captured_source_units": captured_amount,
            "fraud_value_capture_pct": 100 * captured_amount / total_fraud_amount if total_fraud_amount else 0.0,
        })
    return output


def _write_model_and_metrics(
    connection: duckdb.DuckDBPyConnection,
    scratch: Path,
    train_info: dict[str, int],
) -> dict[str, Any]:
    train_count = _scalar(connection, "SELECT COUNT(*) FROM sampled_train")
    train_fraud = _scalar(connection, "SELECT COUNT(*) FROM sampled_train WHERE is_fraud")
    train_non_fraud = train_count - train_fraud
    actual_ratio = train_non_fraud / train_fraud if train_fraud else 0.0
    model_dir = scratch / "models"
    model_dir.mkdir()
    results = {}

    test_rows = _scalar(connection, "SELECT COUNT(*) FROM split_rows WHERE NOT is_train")
    test_data = connection.execute(
        "SELECT * FROM split_rows WHERE NOT is_train ORDER BY event_time, transaction_id"
    ).fetchnumpy()

    for stage, features in FEATURE_STAGES.items():
        train_matrix, train_labels, _ = _feature_matrix(connection, "sampled_train", features)
        test_matrix = np.column_stack([test_data[name] for name in features]).astype(np.float32, copy=False)
        test_labels = np.asarray(test_data["is_fraud"], dtype=np.bool_)
        test_amounts = np.asarray(test_data["amount"], dtype=np.float64)
        if not np.isfinite(test_matrix).all() or test_labels.size != test_rows:
            raise ValueError("Invalid chronological test matrix.")

        train_matrix_data = xgb.DMatrix(train_matrix, label=train_labels.astype(np.float32), feature_names=list(features))
        test_matrix_data = xgb.DMatrix(test_matrix, feature_names=list(features))
        booster = xgb.train(XGBOOST_PARAMETERS, train_matrix_data, num_boost_round=BOOSTED_ROUNDS)
        scores = np.asarray(booster.predict(test_matrix_data), dtype=np.float64)
        model_path = model_dir / f"{stage.lower()}.json"
        booster.save_model(model_path)
        results[stage] = {
            "feature_count": len(features),
            "feature_order": list(features),
            "auprc_average_precision": _average_precision(test_labels, scores),
            "review_capacity_capture": _capture_metrics(test_labels, scores, test_amounts),
            "model_file": f"models/{model_path.name}",
            "model_sha256": _sha256(model_path),
        }
        del booster, train_matrix_data, test_matrix_data, train_matrix, train_labels, test_matrix, test_labels, test_amounts, scores
    del test_data

    train_info["actual_train_negative_to_positive_ratio"] = actual_ratio
    train_info["target_train_negative_to_positive_ratio"] = NEGATIVE_PER_POSITIVE
    return results


def _fingerprints(input_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        filename: {
            "bytes": (input_dir / filename).stat().st_size,
            "sha256": _sha256(input_dir / filename),
            "mtime_ns": (input_dir / filename).stat().st_mtime_ns,
        }
        for filename in INPUT_FILES
    }


def run_evaluation(*, input_dir: Path, output_name: str) -> dict[str, Any]:
    if not output_name.isascii() or not output_name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("output_name must contain only ASCII letters, digits, hyphens, and underscores.")
    input_dir = input_dir.expanduser().resolve()
    if not input_dir.is_dir():
        raise ValueError("input_dir must reference an extracted dataset directory.")
    for filename in INPUT_FILES:
        if not (input_dir / filename).is_file():
            raise ValueError(f"Required dataset file is missing: {filename}")

    root = Path(__file__).resolve().parents[1]
    local_data = (root / "local-data").resolve()
    local_data.mkdir(parents=True, exist_ok=True)
    output_dir = (local_data / output_name).resolve()
    if not output_dir.is_relative_to(local_data) or output_dir == local_data:
        raise ValueError("Output must be a named subdirectory of local-data.")
    if output_dir.exists():
        raise FileExistsError("Output already exists; choose a new output name.")

    input_fingerprints = _fingerprints(input_dir)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".public-eval-", dir=local_data) as scratch_name:
        scratch = Path(scratch_name)
        duckdb_temp = scratch / "duckdb-temp"
        duckdb_temp.mkdir()
        labels_csv = scratch / "labels.csv"
        label_counts = _stream_labels(input_dir / "train_fraud_labels.json", labels_csv)
        connection = duckdb.connect(
            database=":memory:",
            config={"threads": "4", "temp_directory": str(duckdb_temp)},
        )
        try:
            row_counts = _materialize_tables(connection, input_dir, labels_csv)
            train_info = _create_split_and_sample(connection)
            results = _write_model_and_metrics(connection, scratch, train_info)
            train_info.update(row_counts)
            manifest = {
                "schema_version": 1,
                "status": "exploratory_provenance_unverified",
                "source": {
                    "dataset_url": DATASET_URL,
                    "reference_version": DATASET_VERSION_REFERENCE,
                    "verification": "caller-supplied files hashed locally; publisher byte-identity not independently verified",
                    "input_hashes": {
                        name: {key: value for key, value in fingerprint.items() if key != "mtime_ns"}
                        for name, fingerprint in input_fingerprints.items()
                    },
                },
                "protocol": {
                    "split": "chronological 80/20 by event_time then transaction_id",
                    "training_negative_sampling": "all positives and up to 20 deterministic-hash-ranked negatives per positive; training only",
                    "random_seed": RANDOM_SEED,
                    "xgboost_parameters": XGBOOST_PARAMETERS,
                    "boosted_rounds": BOOSTED_ROUNDS,
                    "feature_stages": {name: list(features) for name, features in FEATURE_STAGES.items()},
                    "review_capacities_pct": [capacity * 100 for capacity in REVIEW_CAPACITIES],
                    "fraud_amount_definition": "sum of max(source amount, 0) for true-fraud rows in reviewed queue; currency not independently verified",
                    "label_availability_limit": "label presence is used; seven-day C1 lag does not establish true label-arrival time",
                    "score_calibration": "not calibrated; AUPRC and fixed-capacity ranking metrics only",
                },
                "counts": {**label_counts, **train_info},
                "metrics": results,
                "runtime": {
                    "python": platform.python_version(),
                    "duckdb": duckdb.__version__,
                    "xgboost": xgb.__version__,
                    "numpy": np.__version__,
                },
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "publication_clearance": False,
            }
            for filename, original in input_fingerprints.items():
                current = input_dir / filename
                stat = current.stat()
                if stat.st_size != original["bytes"] or stat.st_mtime_ns != original["mtime_ns"]:
                    raise RuntimeError("An input file changed during evaluation.")
            (scratch / "metrics.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            labels_csv.unlink(missing_ok=True)
            shutil.rmtree(duckdb_temp, ignore_errors=True)
            (scratch / "metrics.json").rename(scratch / "evaluation.json")
            os.replace(scratch, output_dir)
        finally:
            connection.close()

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-name", default="public-evaluation-v1")
    args = parser.parse_args()
    result = run_evaluation(input_dir=args.input_dir, output_name=args.output_name)
    print(json.dumps({
        "output": f"local-data/{args.output_name}",
        "status": result["status"],
        "stages": list(result["metrics"]),
        "publication_clearance": result["publication_clearance"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
