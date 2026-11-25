"""Exercise the local graph-to-model orchestration with synthetic fixtures."""

from __future__ import annotations

import numpy as np
import pytest
from rdflib import Graph
import xgboost as xgb

from feature_assembler import C1_FEATURE_ORDER
from local_inference import XGBoostInferenceProvider
from local_scoring_service import LocalFraudScoringService
from rdf_feature_provider import RdfFeatureProvider


SYNTHETIC_GRAPH = """
@prefix tx: <https://example.org/fraud/transactions#> .
@prefix feat: <https://example.org/fraud/features#> .
@prefix demo: <https://example.org/fraud/demo/> .
@prefix usr: <https://example.org/fraud/users#> .
@prefix card: <https://example.org/fraud/cards#> .

demo:user a usr:User ; usr:UsersData.id 1 ; usr:UsersData.currentAge 35 ;
    usr:UsersData.creditScore 650 ; usr:UsersData.yearlyIncome "$60,000" .
demo:card a card:Card ; card:CardsData.id 10 ; card:CardsData.creditLimit "$5,000" .
demo:first a tx:Transaction ; tx:TransactionsData.id 1 ; tx:TransactionsData.cardId 10 ;
    tx:TransactionsData.merchantId 20 ; tx:TransactionsData.amount "$10" ;
    feat:transactionTimeKey 395199 ; feat:isFraud false .
demo:second a tx:Transaction ; tx:TransactionsData.id 2 ; tx:TransactionsData.cardId 10 ;
    tx:TransactionsData.merchantId 20 ; tx:TransactionsData.amount "$30" ;
    feat:transactionTimeKey 395200 ; feat:isFraud true .
"""


@pytest.fixture
def model_path(tmp_path):
    matrix = xgb.DMatrix(
        np.asarray([
            [60, 60000, 5000, 35, 650, 2, 20, 3, 168, 2, 1, 50, 1, 1, 100],
            [10, 30000, 1000, 22, 500, 0, 0, 0, 0, 100, 80, 80, 10, 8, 80],
            [500, 90000, 10000, 55, 800, 4, 25, 20, 24, 10, 0, 0, 5, 0, 0],
            [1000, 120000, 20000, 45, 750, 8, 100, 10, 24, 200, 20, 10, 20, 5, 25],
        ], dtype=np.float32),
        label=np.asarray([0, 1, 0, 1], dtype=np.float32),
        feature_names=C1_FEATURE_ORDER,
    )
    model = xgb.train(
        {"objective": "binary:logistic", "max_depth": 2, "seed": 11, "nthread": 1},
        matrix,
        num_boost_round=4,
    )
    path = tmp_path / "synthetic-model.json"
    model.save_model(path)
    return path


def test_score_transaction_composes_graph_features_and_local_model(model_path):
    graph = Graph().parse(data=SYNTHETIC_GRAPH, format="turtle")
    feature_provider = RdfFeatureProvider(graph)
    inference_provider = XGBoostInferenceProvider(
        model_path=model_path,
        native_probability_is_fraud=True,
        fraud_threshold=0.5,
    )
    service = LocalFraudScoringService(
        feature_provider=feature_provider,
        inference_provider=inference_provider,
    )

    result = service.score_transaction(
        amount=60.0,
        client_id=1,
        card_id=10,
        merchant_id=20,
        scoring_time_key=1_000_000,
    )

    assert set(result) == {
        "prediction", "fraud_confidence", "non_fraud_confidence",
        "evidence", "timings_ms", "model_parity",
    }
    assert type(result["prediction"]) is bool
    assert result["fraud_confidence"] + result["non_fraud_confidence"] == pytest.approx(1.0)
    assert result["evidence"] == {
        "card_prior_txn_count": 2,
        "card_prior_avg_amount": 20.0,
        "amount_vs_card_avg": 3.0,
        "time_since_prev_card_txn": 168.0,
        "merchant_prior_txn_count": 2,
        "merchant_prior_fraud_count": 1,
        "merchant_prior_fraud_rate_pct": 50.0,
        "merchant_prior_unique_cards": 1,
        "merchant_prior_unique_fraud_cards": 1,
        "merchant_prior_fraud_card_ratio_pct": 100.0,
    }
    assert set(result["timings_ms"]) == {
        "a0", "b1", "c1", "assembly", "model_inference", "feature_generation", "end_to_end",
    }
    assert all(value >= 0 for value in result["timings_ms"].values())
    assert result["model_parity"] == "not_exactly_equivalent_to_ai_studio"
