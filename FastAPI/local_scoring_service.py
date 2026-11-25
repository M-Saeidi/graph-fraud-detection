"""Local orchestration for graph features and portfolio-demo inference."""

from __future__ import annotations

import time
from typing import Any

from feature_assembler import assemble_c1_features, as_ordered_row, calculate_b1


EVIDENCE_FEATURE_NAMES = (
    "card_prior_txn_count",
    "card_prior_avg_amount",
    "amount_vs_card_avg",
    "time_since_prev_card_txn",
    "merchant_prior_txn_count",
    "merchant_prior_fraud_count",
    "merchant_prior_fraud_rate_pct",
    "merchant_prior_unique_cards",
    "merchant_prior_unique_fraud_cards",
    "merchant_prior_fraud_card_ratio_pct",
)


class LocalFraudScoringService:
    """Assemble the existing C1 inputs and score them with a local provider.

    This is a portfolio demonstration path. Its model output has not achieved
    exact parity with the original AI Studio scorer.
    """

    PARITY_STATUS = "not_exactly_equivalent_to_ai_studio"

    def __init__(self, *, feature_provider: Any, inference_provider: Any) -> None:
        self.feature_provider = feature_provider
        self.inference_provider = inference_provider

    def score_transaction(
        self,
        *,
        amount: float,
        client_id: int,
        card_id: int,
        merchant_id: int,
        scoring_time_key: int,
    ) -> dict[str, Any]:
        end_to_end_start = time.perf_counter()
        timings: dict[str, float] = {}

        stage_start = time.perf_counter()
        a0 = self.feature_provider.get_a0(client_id=client_id, card_id=card_id)
        timings["a0"] = (time.perf_counter() - stage_start) * 1000.0

        stage_start = time.perf_counter()
        b1_state = self.feature_provider.get_b1_state(
            card_id=card_id,
            scoring_time_key=scoring_time_key,
        )
        b1 = calculate_b1(
            amount=amount,
            scoring_time_key=scoring_time_key,
            b1_state=b1_state,
        )
        timings["b1"] = (time.perf_counter() - stage_start) * 1000.0

        stage_start = time.perf_counter()
        c1 = self.feature_provider.get_c1_features(
            merchant_id=merchant_id,
            scoring_time_key=scoring_time_key,
        )
        timings["c1"] = (time.perf_counter() - stage_start) * 1000.0

        stage_start = time.perf_counter()
        features = assemble_c1_features(amount=amount, a0=a0, b1=b1, c1=c1)
        as_ordered_row(features)
        timings["assembly"] = (time.perf_counter() - stage_start) * 1000.0
        evidence = {
            name: features[name]
            for name in EVIDENCE_FEATURE_NAMES
        }

        stage_start = time.perf_counter()
        prediction = self.inference_provider.score(features)
        timings["model_inference"] = (time.perf_counter() - stage_start) * 1000.0
        timings["feature_generation"] = sum(
            timings[name] for name in ("a0", "b1", "c1", "assembly")
        )
        timings["end_to_end"] = (time.perf_counter() - end_to_end_start) * 1000.0

        return {
            **prediction,
            "evidence": evidence,
            "timings_ms": {name: round(value, 3) for name, value in timings.items()},
            "model_parity": self.PARITY_STATUS,
        }
