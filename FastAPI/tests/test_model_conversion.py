"""No original model or transaction records are required by these tests."""

import base64
import csv
import hashlib
import json
import struct

import pytest

import convert_model as conversion
from feature_assembler import C1_FEATURE_ORDER, as_ordered_row


@pytest.fixture
def wrapper():
    columns = [{"name": name, "type": "Integer" if name in conversion.INTEGER_FEATURES else "Real"} for name in C1_FEATURE_ORDER]
    columns.insert(3, {"name": "isFraud", "type": "Nominal", "role": "label", "dictionary": [None, "false", "true"]})
    payload = bytearray(140)
    payload[:4] = b"binf"
    struct.pack_into("<I", payload, 8, 15)
    return {"rm_object_type": "com.rapidminer.extension.xgboost.model.XGBoostModel", "rm_object_version": "12.1.1",
            "headerTable": {"width": 16, "columns": columns}, "iterations": 3,
            "parameters": {"objective": "binary:logistic", "booster": "gbtree"},
            "booster": base64.b64encode(payload).decode("ascii")}


def write_wrapper(tmp_path, wrapper):
    path = tmp_path / "fixture.rmtabmod"
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    return path


def test_static_wrapper_checks(tmp_path, wrapper):
    source = write_wrapper(tmp_path, wrapper)
    reviewed = conversion.read_reviewed_model(source)
    assert reviewed.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert reviewed.payload.startswith(b"binf")
    assert reviewed.iterations == 3


@pytest.mark.parametrize("field,value", [("rm_object_type", "other"), ("rm_object_version", "other"), ("iterations", True), ("iterations", 0), ("booster", "invalid%")])
def test_rejects_unreviewed_wrapper(tmp_path, wrapper, field, value):
    wrapper[field] = value
    with pytest.raises(ValueError):
        conversion.read_reviewed_model(write_wrapper(tmp_path, wrapper))


@pytest.mark.parametrize("defect", ["order", "role", "label", "type", "width", "objective", "signature", "feature_count"])
def test_rejects_contract_drift(tmp_path, wrapper, defect):
    columns = wrapper["headerTable"]["columns"]
    if defect == "order":
        columns[0], columns[1] = columns[1], columns[0]
    elif defect == "role":
        columns[0]["role"] = "id"
    elif defect == "label":
        columns[3]["dictionary"] = [None, "true", "false"]
    elif defect == "type":
        columns[0]["type"] = "Nominal"
    elif defect == "width":
        wrapper["headerTable"]["width"] = 15
    elif defect == "objective":
        wrapper["parameters"]["objective"] = "reg:squarederror"
    else:
        payload = bytearray(base64.b64decode(wrapper["booster"]))
        if defect == "signature":
            payload[:4] = b"oops"
        else:
            struct.pack_into("<I", payload, 8, 14)
        wrapper["booster"] = base64.b64encode(payload).decode("ascii")
    with pytest.raises(ValueError):
        conversion.read_reviewed_model(write_wrapper(tmp_path, wrapper))


def test_duplicate_json_fields(tmp_path):
    source = tmp_path / "duplicate.json"
    source.write_text('{"booster":"first","booster":"second"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        conversion.read_reviewed_model(source)


def test_oversized_wrapper(tmp_path, wrapper, monkeypatch):
    monkeypatch.setattr(conversion, "MAX_WRAPPER_BYTES", 10)
    with pytest.raises(ValueError, match="size limit"):
        conversion.read_reviewed_model(write_wrapper(tmp_path, wrapper))


def test_probe_rows_are_deterministic_and_follow_contract():
    rows = conversion.probe_features()
    assert rows == conversion.probe_features()
    assert len(rows) == 72
    for row in rows:
        assert list(row) == C1_FEATURE_ORDER
        assert "isFraud" not in row
        assert row["merchant_prior_fraud_count"] <= row["merchant_prior_txn_count"]
        assert row["merchant_prior_unique_fraud_cards"] <= row["merchant_prior_unique_cards"]


@pytest.fixture
def native_wrapper(tmp_path, wrapper):
    xgb = pytest.importorskip("xgboost", reason="Install requirements-model-conversion.txt for native checks")
    np = pytest.importorskip("numpy")
    rows = conversion.probe_features()
    matrix = xgb.DMatrix(np.asarray([as_ordered_row(row) for row in rows], dtype=np.float32),
                         label=[int(row["amount"] > 100) for row in rows])
    booster = xgb.train({"objective": "binary:logistic", "max_depth": 2, "seed": 7, "nthread": 1}, matrix, num_boost_round=3)
    booster.set_attr(unreviewed_metadata="DO_NOT_EXPORT")
    with pytest.warns(UserWarning, match="deprecated binary model format"):
        payload = booster.save_raw(raw_format="deprecated")
    wrapper["booster"] = base64.b64encode(payload).decode("ascii")
    return write_wrapper(tmp_path, wrapper)


def test_native_conversion_and_no_overwrite(tmp_path, native_wrapper, monkeypatch):
    monkeypatch.setattr(conversion, "__file__", str(tmp_path / "FastAPI" / "convert_model.py"))
    original = native_wrapper.read_bytes()
    output = tmp_path / "local-data" / "converted"
    manifest = conversion.convert_model(native_wrapper, output)
    assert native_wrapper.read_bytes() == original
    assert manifest["release_clearance"] is False
    assert manifest["validation"]["vendor_parity"] == "not_tested"
    assert manifest["validation"]["probability"]["maximum_absolute_difference"] == 0
    assert manifest["validation"]["margin"]["maximum_absolute_difference"] == 0
    for filename, key in [("model.json", "model_sha256"), ("probes.json", "probes_sha256"), ("reference_inputs.csv", "reference_inputs_sha256")]:
        content = (output / filename).read_bytes()
        assert hashlib.sha256(content).hexdigest() == manifest[key]
        assert b"DO_NOT_EXPORT" not in content
    with (output / "reference_inputs.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == C1_FEATURE_ORDER
        reference_rows = [{key: float(value) for key, value in row.items()} for row in reader]
    assert reference_rows == conversion.probe_features()
    assert str(tmp_path) not in json.dumps(manifest)
    with pytest.raises(FileExistsError):
        conversion.convert_model(native_wrapper, output)


def test_native_count_mismatch_produces_no_output(tmp_path, native_wrapper, monkeypatch):
    monkeypatch.setattr(conversion, "__file__", str(tmp_path / "FastAPI" / "convert_model.py"))
    wrapper = json.loads(native_wrapper.read_text())
    wrapper["iterations"] = 4
    native_wrapper.write_text(json.dumps(wrapper), encoding="utf-8")
    output = tmp_path / "local-data" / "rejected"
    with pytest.raises(ValueError, match="iteration count"):
        conversion.convert_model(native_wrapper, output)
    assert not output.exists()


def test_output_outside_destination_rejected(tmp_path, native_wrapper, monkeypatch):
    monkeypatch.setattr(conversion, "__file__", str(tmp_path / "FastAPI" / "convert_model.py"))
    with pytest.raises(ValueError, match="local-data"):
        conversion.convert_model(native_wrapper, tmp_path / "outside")


def test_prediction_changes_are_rejected():
    np = pytest.importorskip("numpy")
    with pytest.raises(ValueError, match="tolerance"):
        conversion.compare_predictions(np.array([0.1]), np.array([0.2]))
    with pytest.raises(ValueError, match="non-finite"):
        conversion.compare_predictions(np.array([0.1]), np.array([float("nan")]))


@pytest.mark.parametrize("name", ["../outside", "nested/path", "", "..", "bad:name"])
def test_cli_rejects_invalid_output_name(monkeypatch, name):
    monkeypatch.setattr("sys.argv", ["convert_model", "--source-model", "unused", "--acknowledge-local-model-review", "--output-name", name])
    with pytest.raises(SystemExit) as error:
        conversion.main()
    assert error.value.code == 2


def test_cli_requires_model_review_acknowledgement(monkeypatch):
    monkeypatch.setattr("sys.argv", ["convert_model", "--source-model", "unused"])
    with pytest.raises(SystemExit) as error:
        conversion.main()
    assert error.value.code == 2