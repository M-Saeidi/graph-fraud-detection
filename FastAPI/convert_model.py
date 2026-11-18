"""Locally convert a reviewed model; native round-trip checks are not vendor parity."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import platform
import struct
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path

from feature_assembler import C1_FEATURE_ORDER, as_ordered_row, assemble_c1_features, calculate_b1


MAX_WRAPPER_BYTES = 16 * 1024 * 1024
CONVERSION_VERSION = "2.1.4"
ROUND_TRIP_ATOL = 1e-7
INTEGER_FEATURES = {
    "currentAge", "creditScore", "card_prior_txn_count", "merchant_prior_txn_count",
    "merchant_prior_fraud_count", "merchant_prior_unique_cards", "merchant_prior_unique_fraud_cards",
}


@dataclass(frozen=True)
class ReviewedModel:
    payload: bytes
    source_sha256: str
    iterations: int


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field in model wrapper.")
        result[key] = value
    return result


def read_reviewed_model(source: Path) -> ReviewedModel:
    with source.open("rb") as stream:
        raw = stream.read(MAX_WRAPPER_BYTES + 1)
    if len(raw) > MAX_WRAPPER_BYTES:
        raise ValueError("Model wrapper exceeds the local size limit.")
    model = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(model, dict) or model.get("rm_object_type") != "com.rapidminer.extension.xgboost.model.XGBoostModel":
        raise ValueError("Unsupported model wrapper type.")
    if model.get("rm_object_version") != "12.1.1":
        raise ValueError("Unreviewed wrapper version.")
    header = model.get("headerTable")
    if not isinstance(header, dict) or header.get("width") != 16:
        raise ValueError("Unexpected model header width.")
    columns = header.get("columns")
    if not isinstance(columns, list) or len(columns) != 16 or not all(isinstance(column, dict) for column in columns):
        raise ValueError("Invalid model header columns.")
    labels = [column for column in columns if column.get("role") == "label"]
    predictors = [column for column in columns if column.get("role") != "label"]
    if len(labels) != 1 or labels[0].get("name") != "isFraud" or labels[0].get("type") != "Nominal" or labels[0].get("dictionary") != [None, "false", "true"]:
        raise ValueError("Unexpected label metadata.")
    if [column.get("name") for column in predictors] != C1_FEATURE_ORDER:
        raise ValueError("Predictor names/order differ from the C1 contract.")
    for column in predictors:
        expected_type = "Integer" if column["name"] in INTEGER_FEATURES else "Real"
        if column.get("type") != expected_type or column.get("role") not in (None, ""):
            raise ValueError("Unexpected predictor type or role.")
    parameters = model.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("objective") != "binary:logistic" or parameters.get("booster") != "gbtree":
        raise ValueError("Unsupported model objective or booster.")
    iterations = model.get("iterations")
    if type(iterations) is not int or not 1 <= iterations <= 10_000:
        raise ValueError("Invalid model iteration count.")
    encoded = model.get("booster")
    if not isinstance(encoded, str):
        raise ValueError("Expected a Base64 booster string.")
    payload = base64.b64decode(encoded, validate=True)
    if len(payload) < 140 or payload[:4] != b"binf" or struct.unpack_from("<I", payload, 8)[0] != len(C1_FEATURE_ORDER):
        raise ValueError("Unexpected legacy booster header.")
    return ReviewedModel(payload, hashlib.sha256(raw).hexdigest(), iterations)


def probe_features() -> list[dict[str, int | float]]:
    """Generate consistent feature rows without using source transaction data."""
    rows = []
    profiles = [(35, 650, 60000, 5000), (22, 500, 24000, 1000), (55, 800, 120000, 20000)]
    amounts = [-10, 0, 10, 75, 500, 1000, 5000, 10000]
    for age, score, income, limit in profiles:
        for amount in amounts:
            for history in ("empty", "ordinary", "high_fraud"):
                empty = history == "empty"
                fraud_count = 0 if empty else (2 if history == "ordinary" else 80)
                fraud_cards = 0 if empty else (1 if history == "ordinary" else 8)
                b1_state = {"prior_count": 0 if empty else 4, "prior_avg_amount": None if empty else 25,
                            "previous_transaction_time_key": None if empty else 10000}
                rows.append(assemble_c1_features(
                    amount=amount,
                    a0={"currentAge": age, "creditScore": score, "yearlyIncome": income, "creditLimit": limit},
                    b1=calculate_b1(amount=amount, scoring_time_key=19000, b1_state=b1_state),
                    c1={"merchant_prior_txn_count": 0 if empty else 100,
                        "merchant_prior_fraud_count": fraud_count,
                        "merchant_prior_fraud_rate_pct": float(fraud_count),
                        "merchant_prior_unique_cards": 0 if empty else 10,
                        "merchant_prior_unique_fraud_cards": fraud_cards,
                        "merchant_prior_fraud_card_ratio_pct": float(fraud_cards * 10)},
                ))
    return rows


def compare_predictions(before, after) -> dict:
    import numpy as np

    if before.shape != after.shape or not before.size or not np.isfinite(before).all() or not np.isfinite(after).all():
        raise ValueError("Invalid prediction shape or non-finite output.")
    maximum = float(np.max(np.abs(before - after)))
    if not np.allclose(before, after, rtol=0, atol=ROUND_TRIP_ATOL):
        raise ValueError("Native round-trip predictions exceed the declared tolerance.")
    return {"maximum_absolute_difference": maximum, "absolute_tolerance": ROUND_TRIP_ATOL, "relative_tolerance": 0}


def convert_model(source: Path, output: Path) -> dict:
    import numpy as np
    import scipy
    import xgboost as xgb

    if xgb.__version__ != CONVERSION_VERSION:
        raise ValueError("Use the pinned legacy conversion runtime.")
    root = Path(__file__).resolve().parents[1] / "local-data"
    output = output.resolve()
    if not output.is_relative_to(root.resolve()) or output == root.resolve():
        raise ValueError("Output must be inside this edition's local-data directory.")
    if output.exists():
        raise FileExistsError("Conversion output already exists; refusing overwrite.")
    reviewed = read_reviewed_model(source)
    booster = xgb.Booster(params={"nthread": 1, "device": "cpu"})
    warning_codes = []
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        booster.load_model(bytearray(reviewed.payload))
    for warning in recorded:
        if warning.category is UserWarning and "Loading model from XGBoost < 1.0.0" in str(warning.message):
            warning_codes.append("legacy_model_compatibility")
        else:
            raise ValueError("Unexpected native load warning; review locally before proceeding.")
    config = json.loads(booster.save_config())["learner"]
    if booster.num_features() != len(C1_FEATURE_ORDER) or booster.num_boosted_rounds() != reviewed.iterations:
        raise ValueError("Native feature or iteration count differs from the wrapper.")
    if config["objective"]["name"] != "binary:logistic" or config["gradient_booster"]["name"] != "gbtree":
        raise ValueError("Native model objective or booster differs from the wrapper.")
    rows = probe_features()
    matrix = xgb.DMatrix(np.asarray([as_ordered_row(row) for row in rows], dtype=np.float32), feature_names=C1_FEATURE_ORDER)
    before_probability = booster.predict(matrix)
    before_margin = booster.predict(matrix, output_margin=True)
    if not ((before_probability >= 0) & (before_probability <= 1)).all():
        raise ValueError("Native probability is outside the expected range.")
    booster.set_attr(**{key: None for key in booster.attributes()})
    booster.feature_names = C1_FEATURE_ORDER.copy()
    booster.feature_types = ["q"] * len(C1_FEATURE_ORDER)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".model-conversion-", dir=output.parent) as temporary:
        candidate = Path(temporary) / "model.json"
        booster.save_model(candidate)
        restored = xgb.Booster(params={"nthread": 1, "device": "cpu"})
        restored.load_model(candidate)
        probability_check = compare_predictions(before_probability, restored.predict(matrix))
        margin_check = compare_predictions(before_margin, restored.predict(matrix, output_margin=True))
        if not np.array_equal(before_probability >= 0.5, restored.predict(matrix) >= 0.5):
            raise ValueError("Diagnostic 0.5 threshold decision changed during conversion.")
        if restored.attributes() or restored.feature_names != C1_FEATURE_ORDER:
            raise ValueError("Converted metadata failed review.")
        model_bytes = candidate.read_bytes()
        probes = {"schema_version": 1, "feature_order": C1_FEATURE_ORDER, "rows": rows,
                  "native_probabilities": before_probability.tolist(), "native_margins": before_margin.tolist(),
                  "class_mapping": "unverified; probabilities are not named fraud confidences"}
        probe_bytes = (json.dumps(probes, indent=2, sort_keys=True) + "\n").encode("utf-8")
        csv_stream = io.StringIO(newline="")
        writer = csv.DictWriter(csv_stream, fieldnames=C1_FEATURE_ORDER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        input_bytes = csv_stream.getvalue().encode("utf-8")
        manifest = {
            "schema_version": 1,
            "status": "quarantined_native_round_trip_passed",
            "source_sha256": reviewed.source_sha256,
            "legacy_payload_sha256": hashlib.sha256(reviewed.payload).hexdigest(),
            "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
            "probes_sha256": hashlib.sha256(probe_bytes).hexdigest(),
            "reference_inputs_sha256": hashlib.sha256(input_bytes).hexdigest(),
            "runtime": {"python": platform.python_version(), "xgboost": xgb.__version__, "numpy": np.__version__, "scipy": scipy.__version__},
            "model": {"objective": "binary:logistic", "booster": "gbtree", "boosted_rounds": reviewed.iterations,
                      "feature_order": C1_FEATURE_ORDER, "header_label_dictionary": [None, "false", "true"]},
            "validation": {"rows": len(rows), "probability": probability_check, "margin": margin_check,
                           "diagnostic_threshold": 0.5, "diagnostic_threshold_changes": 0,
                           "vendor_parity": "not_tested", "class_mapping": "unverified", "load_warning_codes": warning_codes},
            "release_clearance": False,
        }
        if read_reviewed_model(source).source_sha256 != reviewed.source_sha256:
            raise ValueError("Source model changed during conversion.")
        output.mkdir(exist_ok=False)
        for filename, content in [("model.json", model_bytes), ("probes.json", probe_bytes),
                                  ("reference_inputs.csv", input_bytes),
                                  ("manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))]:
            with (output / filename).open("xb") as stream:
                stream.write(content)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-model", required=True, type=Path)
    parser.add_argument("--acknowledge-local-model-review", required=True, action="store_true")
    parser.add_argument("--output-name", default="model-conversion")
    args = parser.parse_args()
    if not args.output_name.isascii() or not args.output_name.replace("-", "").replace("_", "").isalnum():
        parser.error("Output name must contain only ASCII letters, digits, hyphens, and underscores.")
    output = Path(__file__).resolve().parents[1] / "local-data" / args.output_name
    manifest = convert_model(args.source_model, output)
    print(json.dumps({"output": f"local-data/{args.output_name}", "status": manifest["status"], "validation": manifest["validation"]}, sort_keys=True))


if __name__ == "__main__":
    main()