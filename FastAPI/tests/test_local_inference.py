"""Tests for the vendor-independent local model boundary."""

from __future__ import annotations

import json

import pytest

from feature_assembler import C1_FEATURE_ORDER
from local_inference import LocalInferenceError, XGBoostInferenceProvider


@pytest.fixture
def model_path(tmp_path):
    xgb = pytest.importorskip("xgboost")
    np = pytest.importorskip("numpy")

    features = [
        [75, 60000, 5000, 35, 650, 4, 25, 3, 2.5, 20, 2, 10, 8, 1, 12.5],
        [500, 20000, 1000, 22, 500, 0, 0, 0, 0, 100, 80, 80, 10, 8, 80],
        [10, 90000, 10000, 55, 800, 2, 10, 1, 1, 10, 0, 0, 5, 0, 0],
        [1000, 120000, 20000, 45, 750, 8, 100, 10, 24, 200, 20, 10, 20, 5, 25],
    ]
    matrix = xgb.DMatrix(
        np.asarray(features, dtype=np.float32),
        label=np.asarray([0, 1, 0, 1], dtype=np.float32),
        feature_names=C1_FEATURE_ORDER,
    )
    model = xgb.train(
        {"objective": "binary:logistic", "max_depth": 2, "seed": 7, "nthread": 1},
        matrix,
        num_boost_round=4,
    )
    path = tmp_path / "model.json"
    model.save_model(path)
    return path


def valid_features():
    values = [75, 60000, 5000, 35, 650, 4, 25, 3, 2.5, 20, 2, 10, 8, 1, 12.5]
    return dict(zip(C1_FEATURE_ORDER, values))


def test_score_returns_existing_contract(model_path):
    provider = XGBoostInferenceProvider(
        model_path=model_path,
        native_probability_is_fraud=True,
        fraud_threshold=0.5,
    )
    result = provider.score(valid_features())
    assert set(result) == {"prediction", "fraud_confidence", "non_fraud_confidence"}
    assert type(result["prediction"]) is bool
    assert 0 <= result["fraud_confidence"] <= 1
    assert 0 <= result["non_fraud_confidence"] <= 1
    assert abs(result["fraud_confidence"] + result["non_fraud_confidence"] - 1) < 1e-12


@pytest.mark.parametrize("mapping", [True, False])
def test_mapping_is_explicit(model_path, mapping):
    provider = XGBoostInferenceProvider(
        model_path=model_path,
        native_probability_is_fraud=mapping,
    )
    a = provider.score(valid_features())
    b = provider.score(valid_features())
    assert a == b
    if mapping:
        assert a["fraud_confidence"] + a["non_fraud_confidence"] == 1
    else:
        assert a["fraud_confidence"] + a["non_fraud_confidence"] == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf")])

def test_rejects_nonfinite_feature(model_path, value):
    features = valid_features()
    features["amount"] = value
    provider = XGBoostInferenceProvider(model_path=model_path, native_probability_is_fraud=True)
    with pytest.raises(LocalInferenceError, match="finite"):
        provider.score(features)


def test_rejects_missing_and_extra_features(model_path):
    provider = XGBoostInferenceProvider(model_path=model_path, native_probability_is_fraud=True)
    missing = valid_features()
    del missing["amount"]
    with pytest.raises(LocalInferenceError, match="exactly"):
        provider.score(missing)

    extra = valid_features()
    extra["unexpected"] = 1
    with pytest.raises(LocalInferenceError, match="exactly"):
        provider.score(extra)


@pytest.mark.parametrize("bad_features", [
    {"amount": True},
    {"amount": "75"},
])
def test_rejects_boolean_or_string_amount(model_path, bad_features):
    provider = XGBoostInferenceProvider(model_path=model_path, native_probability_is_fraud=True)
    features = valid_features()
    features.update(bad_features)
    with pytest.raises(LocalInferenceError, match="numeric"):
        provider.score(features)


@pytest.mark.parametrize("threshold", [True, -0.1, 1.1, float("nan")])
def test_rejects_invalid_threshold(model_path, threshold):
    with pytest.raises(LocalInferenceError, match="threshold"):
        XGBoostInferenceProvider(
            model_path=model_path,
            native_probability_is_fraud=True,
            fraud_threshold=threshold,
        )


def test_requires_mapping_flag(model_path):
    with pytest.raises(TypeError):
        XGBoostInferenceProvider(model_path=model_path)


def test_rejects_missing_model(tmp_path):
    with pytest.raises(LocalInferenceError, match="does not exist"):
        XGBoostInferenceProvider(model_path=tmp_path / "missing.json", native_probability_is_fraud=True)


def test_feature_drift_is_rejected(tmp_path):
    xgb = pytest.importorskip("xgboost")
    np = pytest.importorskip("numpy")
    matrix = xgb.DMatrix(
        np.asarray([[1, 2, 3]], dtype=np.float32),
        label=np.asarray([0], dtype=np.float32),
        feature_names=["wrong_a", "wrong_b", "wrong_c"],
    )
    model = xgb.train({"objective": "binary:logistic", "nthread": 1}, matrix, num_boost_round=1)
    path = tmp_path / "wrong.json"
    model.save_model(path)
    with pytest.raises(LocalInferenceError, match="feature count"):
        XGBoostInferenceProvider(model_path=path, native_probability_is_fraud=True)
