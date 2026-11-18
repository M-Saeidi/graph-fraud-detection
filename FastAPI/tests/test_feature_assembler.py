"""Contract tests with hand-authored synthetic values, not replay data."""

from __future__ import annotations

import pytest

from feature_assembler import (
    C1_FEATURE_ORDER,
    as_ordered_row,
    assemble_c1_features,
    calculate_b1,
)


@pytest.mark.unit
def test_c1_feature_contract_contains_exactly_15_features():
    assert len(C1_FEATURE_ORDER) == 15
    assert C1_FEATURE_ORDER == [
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


@pytest.mark.unit
def test_calculate_b1_matches_synthetic_history():
    result = calculate_b1(
        amount=75.0,
        scoring_time_key=20_000,
        b1_state={
            "prior_count": 4,
            "prior_avg_amount": 25.0,
            "previous_transaction_time_key": 11_000,
        },
    )
    assert result == {
        "card_prior_txn_count": 4,
        "card_prior_avg_amount": 25.0,
        "amount_vs_card_avg": 3.0,
        "time_since_prev_card_txn": 2.5,
    }


@pytest.mark.unit
@pytest.mark.parametrize("b1_state", [
    {},
    {"prior_count": 0, "prior_avg_amount": None, "previous_transaction_time_key": None},
])
def test_calculate_b1_zero_history_uses_frozen_defaults(b1_state):
    result = calculate_b1(amount=75.0, scoring_time_key=20_000, b1_state=b1_state)
    assert result == {
        "card_prior_txn_count": 0,
        "card_prior_avg_amount": 0.0,
        "amount_vs_card_avg": 0.0,
        "time_since_prev_card_txn": 0.0,
    }


@pytest.fixture
def synthetic_feature_groups():
    return {
        "a0": {
            "currentAge": 35,
            "creditScore": 650,
            "yearlyIncome": 60_000.0,
            "creditLimit": 5_000.0,
        },
        "b1": {
            "card_prior_txn_count": 4,
            "card_prior_avg_amount": 25.0,
            "amount_vs_card_avg": 3.0,
            "time_since_prev_card_txn": 2.5,
        },
        "c1": {
            "merchant_prior_txn_count": 20,
            "merchant_prior_fraud_count": 2,
            "merchant_prior_fraud_rate_pct": 10.0,
            "merchant_prior_unique_cards": 8,
            "merchant_prior_unique_fraud_cards": 1,
            "merchant_prior_fraud_card_ratio_pct": 12.5,
        },
    }


@pytest.mark.unit
def test_assemble_c1_features_preserves_model_contract(synthetic_feature_groups):
    features = assemble_c1_features(amount=75.0, **synthetic_feature_groups)
    assert list(features) == C1_FEATURE_ORDER
    assert len(features) == 15
    assert as_ordered_row(features) == [
        75.0, 60_000.0, 5_000.0, 35, 650, 4, 25.0, 3.0, 2.5,
        20, 2, 10.0, 8, 1, 12.5,
    ]


@pytest.mark.unit
def test_as_ordered_row_follows_frozen_feature_order():
    features = dict(reversed(list(enumerate(C1_FEATURE_ORDER))))
    values = {name: index for index, name in features.items()}
    assert as_ordered_row(values) == list(range(15))


@pytest.mark.unit
@pytest.mark.parametrize("missing_key", ["prior_avg_amount", "previous_transaction_time_key"])
def test_nonempty_history_requires_complete_state(missing_key):
    state = {"prior_count": 4, "prior_avg_amount": 25.0, "previous_transaction_time_key": 11_000}
    del state[missing_key]
    with pytest.raises(ValueError, match=f"{missing_key} is missing"):
        calculate_b1(amount=75.0, scoring_time_key=20_000, b1_state=state)


@pytest.mark.unit
def test_zero_average_has_defined_ratio():
    result = calculate_b1(
        amount=75.0,
        scoring_time_key=20_000,
        b1_state={"prior_count": 4, "prior_avg_amount": 0.0, "previous_transaction_time_key": 11_000},
    )
    assert result["amount_vs_card_avg"] == 0.0
    assert result["time_since_prev_card_txn"] == 2.5


@pytest.mark.unit
def test_future_history_is_rejected():
    with pytest.raises(ValueError, match="occurs after"):
        calculate_b1(
            amount=75.0,
            scoring_time_key=20_000,
            b1_state={"prior_count": 4, "prior_avg_amount": 25.0, "previous_transaction_time_key": 20_001},
        )


@pytest.mark.unit
def test_equal_timestamps_preserve_existing_zero_recency():
    result = calculate_b1(
        amount=75.0,
        scoring_time_key=20_000,
        b1_state={"prior_count": 4, "prior_avg_amount": 25.0, "previous_transaction_time_key": 20_000},
    )
    assert result["time_since_prev_card_txn"] == 0.0


@pytest.mark.unit
@pytest.mark.parametrize("group_name", ["a0", "b1", "c1"])
def test_missing_feature_groups_are_rejected(synthetic_feature_groups, group_name):
    synthetic_feature_groups[group_name] = {}
    with pytest.raises(ValueError, match=f"Missing required {group_name.upper()} features"):
        assemble_c1_features(amount=75.0, **synthetic_feature_groups)


@pytest.mark.unit
def test_numeric_normalization_and_label_exclusion(synthetic_feature_groups):
    for group in synthetic_feature_groups.values():
        for name, value in group.items():
            group[name] = str(value)
        group["isFraud"] = True
    features = assemble_c1_features(amount="75.0", **synthetic_feature_groups)
    assert "isFraud" not in features
    assert type(features["currentAge"]) is int
    assert type(features["card_prior_txn_count"]) is int
    assert type(features["amount"]) is float
    assert type(features["merchant_prior_fraud_card_ratio_pct"]) is float


@pytest.mark.unit
def test_ordered_row_rejects_missing_feature():
    features = {name: 0 for name in C1_FEATURE_ORDER if name != "amount"}
    with pytest.raises(ValueError, match="Missing features"):
        as_ordered_row(features)