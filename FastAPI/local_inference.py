"""Vendor-independent local inference for a reviewed binary XGBoost model."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from feature_assembler import C1_FEATURE_ORDER


class LocalInferenceError(RuntimeError):
    pass


class XGBoostInferenceProvider:
    """Score exact 15-feature rows with an explicit probability mapping."""

    def __init__(
        self,
        *,
        model_path: str | Path,
        fraud_threshold: float = 0.5,
        native_probability_is_fraud: bool,
        nthread: int = 1,
    ) -> None:
        if type(native_probability_is_fraud) is not bool:
            raise LocalInferenceError("native_probability_is_fraud must be a boolean.")
        if type(fraud_threshold) is not float or not math.isfinite(fraud_threshold):
            raise LocalInferenceError("fraud_threshold must be a finite float.")
        if not 0.0 <= fraud_threshold <= 1.0:
            raise LocalInferenceError("fraud_threshold must be between zero and one.")
        if type(nthread) is not int or not 1 <= nthread <= 64:
            raise LocalInferenceError("nthread must be an integer from 1 to 64.")

        path = Path(model_path).resolve()
        if not path.is_file():
            raise LocalInferenceError("Model file does not exist.")

        try:
            import xgboost as xgb
        except ImportError as exc:
            raise LocalInferenceError("XGBoost runtime is not installed.") from exc

        self.native_probability_is_fraud = native_probability_is_fraud
        self.fraud_threshold = fraud_threshold
        self._booster = xgb.Booster(params={"nthread": nthread, "device": "cpu"})
        try:
            self._booster.load_model(path)
        except Exception as exc:
            raise LocalInferenceError("Could not load the local model.") from exc

        if self._booster.num_features() != len(C1_FEATURE_ORDER):
            raise LocalInferenceError("Model feature count differs from the 15-feature contract.")
        if self._booster.feature_names is not None and list(self._booster.feature_names) != C1_FEATURE_ORDER:
            raise LocalInferenceError("Model feature names differ from the 15-feature contract.")

    def score(self, features: dict[str, int | float]) -> dict[str, Any]:
        if not isinstance(features, dict) or set(features) != set(C1_FEATURE_ORDER):
            raise LocalInferenceError("Expected exactly the 15 named C1 model features.")

        values = []
        for name in C1_FEATURE_ORDER:
            value = features[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise LocalInferenceError(f"Feature {name} must be numeric.")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise LocalInferenceError(f"Feature {name} must be finite.")
            values.append(numeric)

        try:
            import numpy as np
            import xgboost as xgb
        except ImportError as exc:
            raise LocalInferenceError("NumPy/XGBoost runtime is not installed.") from exc

        matrix = xgb.DMatrix(
            np.asarray([values], dtype=np.float32),
            feature_names=C1_FEATURE_ORDER,
        )
        try:
            probabilities = np.asarray(self._booster.predict(matrix), dtype=np.float64).reshape(-1)
        except Exception as exc:
            raise LocalInferenceError("Local model prediction failed.") from exc

        if probabilities.shape != (1,) or not np.isfinite(probabilities).all():
            raise LocalInferenceError("Local model returned no valid probability.")

        native = float(probabilities[0])
        if not 0.0 <= native <= 1.0:
            raise LocalInferenceError("Local model probability is outside zero to one.")

        fraud_probability = native if self.native_probability_is_fraud else 1.0 - native
        non_fraud_probability = 1.0 - fraud_probability
        fraud_probability = min(1.0, max(0.0, fraud_probability))
        prediction = fraud_probability >= self.fraud_threshold

        return {
            "prediction": bool(prediction),
            "fraud_confidence": float(fraud_probability),
            "non_fraud_confidence": float(non_fraud_probability),
        }
