"""Pure feature engineering for the versioned 15-predictor C1 contract.

Inputs are already-retrieved customer, card, and merchant state. No transport
or inference dependency belongs here. Names, order, units, and zero-history
defaults must remain consistent between training and serving.
"""

from __future__ import annotations

from typing import Any


C1_FEATURE_ORDER = [
    "amount",
    "yearlyIncome",
    "creditLimit",
    "currentAge",
    "creditScore",
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
]


def calculate_b1(
    *,
    amount: float,
    scoring_time_key: int,
    b1_state: dict[str, Any],
) -> dict[str, int | float]:
    """Derive card-history predictors, expressing recency in hours.

    Empty history maps to zero-valued predictors. Nonempty history requires
    both an average and a previous timestamp. A zero average yields a zero
    ratio. Future history is rejected; strict earlier-time filtering remains
    the graph provider's responsibility.
    """

    amount = float(amount)
    scoring_time_key = int(scoring_time_key)

    prior_count = int(
        b1_state.get(
            "prior_count",
            0,
        )
        or 0
    )

    prior_avg_amount = b1_state.get(
        "prior_avg_amount"
    )

    previous_transaction_time_key = b1_state.get(
        "previous_transaction_time_key"
    )

    if prior_count == 0:
        return {
            "card_prior_txn_count": 0,
            "card_prior_avg_amount": 0.0,
            "amount_vs_card_avg": 0.0,
            "time_since_prev_card_txn": 0.0,
        }

    if prior_avg_amount is None:
        raise ValueError(
            "Invalid B1 state: prior_count > 0 but "
            "prior_avg_amount is missing."
        )

    if previous_transaction_time_key is None:
        raise ValueError(
            "Invalid B1 state: prior_count > 0 but "
            "previous_transaction_time_key is missing."
        )

    prior_avg_amount = float(
        prior_avg_amount
    )

    previous_transaction_time_key = int(
        previous_transaction_time_key
    )

    if prior_avg_amount == 0.0:
        amount_vs_card_avg = 0.0
    else:
        amount_vs_card_avg = (
            amount
            /
            prior_avg_amount
        )

    time_delta_seconds = (
        scoring_time_key
        -
        previous_transaction_time_key
    )

    if time_delta_seconds < 0:
        raise ValueError(
            "Invalid B1 state: previous transaction occurs after "
            "the scoring transaction."
        )

    time_since_prev_card_txn = (
        time_delta_seconds
        /
        3600.0
    )

    return {
        "card_prior_txn_count":
            prior_count,

        "card_prior_avg_amount":
            prior_avg_amount,

        "amount_vs_card_avg":
            amount_vs_card_avg,

        "time_since_prev_card_txn":
            time_since_prev_card_txn,
    }


def assemble_c1_features(
    *,
    amount: float,
    a0: dict[str, Any],
    b1: dict[str, Any],
    c1: dict[str, Any],
) -> dict[str, int | float]:
    """Assemble transaction, customer/card, and merchant predictors.

    Only the explicit numeric predictors are included; labels and unrelated
    input fields are excluded. Missing required predictors fail immediately.
    """

    required_a0 = {
        "yearlyIncome",
        "creditLimit",
        "currentAge",
        "creditScore",
    }

    required_b1 = {
        "card_prior_txn_count",
        "card_prior_avg_amount",
        "amount_vs_card_avg",
        "time_since_prev_card_txn",
    }

    required_c1 = {
        "merchant_prior_txn_count",
        "merchant_prior_fraud_count",
        "merchant_prior_fraud_rate_pct",
        "merchant_prior_unique_cards",
        "merchant_prior_unique_fraud_cards",
        "merchant_prior_fraud_card_ratio_pct",
    }

    missing_a0 = (
        required_a0
        -
        set(a0)
    )

    missing_b1 = (
        required_b1
        -
        set(b1)
    )

    missing_c1 = (
        required_c1
        -
        set(c1)
    )

    if missing_a0:
        raise ValueError(
            f"Missing required A0 features: {sorted(missing_a0)}"
        )

    if missing_b1:
        raise ValueError(
            f"Missing required B1 features: {sorted(missing_b1)}"
        )

    if missing_c1:
        raise ValueError(
            f"Missing required C1 features: {sorted(missing_c1)}"
        )

    features = {
        "amount":
            float(amount),

        "yearlyIncome":
            float(a0["yearlyIncome"]),

        "creditLimit":
            float(a0["creditLimit"]),

        "currentAge":
            int(a0["currentAge"]),

        "creditScore":
            int(a0["creditScore"]),

        "card_prior_txn_count":
            int(b1["card_prior_txn_count"]),

        "card_prior_avg_amount":
            float(b1["card_prior_avg_amount"]),

        "amount_vs_card_avg":
            float(b1["amount_vs_card_avg"]),

        "time_since_prev_card_txn":
            float(b1["time_since_prev_card_txn"]),

        "merchant_prior_txn_count":
            int(c1["merchant_prior_txn_count"]),

        "merchant_prior_fraud_count":
            int(c1["merchant_prior_fraud_count"]),

        "merchant_prior_fraud_rate_pct":
            float(c1["merchant_prior_fraud_rate_pct"]),

        "merchant_prior_unique_cards":
            int(c1["merchant_prior_unique_cards"]),

        "merchant_prior_unique_fraud_cards":
            int(c1["merchant_prior_unique_fraud_cards"]),

        "merchant_prior_fraud_card_ratio_pct":
            float(c1["merchant_prior_fraud_card_ratio_pct"]),
    }

    actual_features = set(
        features
    )

    expected_features = set(
        C1_FEATURE_ORDER
    )

    if actual_features != expected_features:
        raise RuntimeError(
            "Frozen model feature contract changed unexpectedly.\n"
            f"Missing: {sorted(expected_features - actual_features)}\n"
            f"Unexpected: {sorted(actual_features - expected_features)}"
        )

    return features


def as_ordered_row(
    features: dict[str, int | float],
) -> list[int | float]:
    """Serialize using the explicit contract rather than dictionary order."""

    missing = [
        feature_name
        for feature_name in C1_FEATURE_ORDER
        if feature_name not in features
    ]

    if missing:
        raise ValueError(
            "Cannot construct model row. Missing features: "
            f"{missing}"
        )

    return [
        features[
            feature_name
        ]
        for feature_name in C1_FEATURE_ORDER
    ]