"""HTTP contract tests use an injected fake scorer and no local artifacts."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from rdflib import Graph

from main import FEATURE, PARITY_STATUS, create_app
from time_key import datetime_to_transaction_time_key


class FakeScoringService:
    def __init__(self):
        self.calls = []

    def score_transaction(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "prediction": True,
            "fraud_confidence": 0.8,
            "non_fraud_confidence": 0.2,
            "evidence": {"card_prior_txn_count": 4},
            "timings_ms": {"end_to_end": 1.25},
            "model_parity": PARITY_STATUS,
        }


def test_health_endpoint_marks_demo_parity_status():
    client = TestClient(create_app(scoring_service=FakeScoringService()))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_parity": PARITY_STATUS}


def test_demo_defaults_use_ids_from_injected_local_graph():
    graph = Graph().parse(data="""
@prefix tx: <https://example.org/fraud/transactions#> .
@prefix usr: <https://example.org/fraud/users#> .
@prefix card: <https://example.org/fraud/cards#> .
@prefix demo: <https://example.org/fraud/demo/> .
demo:user usr:UsersData.id 3 .
demo:card card:CardsData.id 4 .
demo:transaction tx:TransactionsData.merchantId 5 .
""", format="turtle")
    scorer = SimpleNamespace(feature_provider=SimpleNamespace(graph=graph))
    client = TestClient(create_app(scoring_service=scorer))

    response = client.get("/demo-defaults")

    assert response.status_code == 200
    result = response.json()
    assert result["amount"] == 75.0
    assert result["client_id"] == 3
    assert result["card_id"] == 4
    assert result["merchant_id"] == 5
    assert datetime.fromisoformat(result["transaction_time"]).tzinfo is None


def test_demo_defaults_are_unavailable_without_a_graph():
    client = TestClient(create_app(scoring_service=FakeScoringService()))
    response = client.get("/demo-defaults")
    assert response.status_code == 503
    assert response.json()["detail"] == "Local graph defaults are unavailable."


def test_demo_defaults_follow_latest_graph_event_and_merchant_lag():
    latest_key = datetime_to_transaction_time_key(datetime(2020, 1, 3, 12))
    graph = Graph()
    graph.parse(data=f"""
@prefix tx: <https://example.org/fraud/transactions#> .
@prefix usr: <https://example.org/fraud/users#> .
@prefix card: <https://example.org/fraud/cards#> .
@prefix feat: <https://example.org/fraud/features#> .
@prefix demo: <https://example.org/fraud/demo/> .
demo:user usr:UsersData.id 3 .
demo:card card:CardsData.id 4 .
demo:transaction tx:TransactionsData.merchantId 5 .
demo:older feat:transactionTimeKey {latest_key - 86400} .
demo:latest feat:transactionTimeKey {latest_key} .
""", format="turtle")
    scorer = SimpleNamespace(feature_provider=SimpleNamespace(graph=graph))
    client = TestClient(create_app(scoring_service=scorer))

    response = client.get("/demo-defaults")

    assert response.status_code == 200
    assert response.json()["transaction_time"] == "2020-01-10T12:00:00"


def test_default_app_loads_bundled_demo_artifacts(monkeypatch):
    monkeypatch.delenv("FRAUD_GRAPH_FILE", raising=False)
    monkeypatch.delenv("FRAUD_MODEL_FILE", raising=False)
    client = TestClient(create_app())

    defaults = client.get("/demo-defaults")
    assert defaults.status_code == 200
    score = client.post("/score", json=defaults.json())
    assert score.status_code == 200
    assert score.json()["model_parity"] == PARITY_STATUS
    assert len(score.json()["evidence"]) == 10


def test_score_endpoint_converts_timestamp_and_returns_scoring_contract():
    scorer = FakeScoringService()
    client = TestClient(create_app(scoring_service=scorer))
    timestamp = datetime(2020, 1, 2, 3, 4, 5)

    response = client.post("/score", json={
        "amount": 75.5,
        "client_id": 1,
        "card_id": 10,
        "merchant_id": 20,
        "transaction_time": timestamp.isoformat(),
    })

    assert response.status_code == 200
    assert response.json() == {
        "prediction": True,
        "fraud_confidence": 0.8,
        "non_fraud_confidence": 0.2,
        "evidence": {"card_prior_txn_count": 4},
        "timings_ms": {"end_to_end": 1.25},
        "model_parity": PARITY_STATUS,
    }
    assert scorer.calls == [{
        "amount": 75.5,
        "client_id": 1,
        "card_id": 10,
        "merchant_id": 20,
        "scoring_time_key": datetime_to_transaction_time_key(timestamp),
    }]


def test_score_rejects_timezone_aware_timestamp():
    client = TestClient(create_app(scoring_service=FakeScoringService()))
    response = client.post("/score", json={
        "amount": 20,
        "client_id": 1,
        "card_id": 10,
        "merchant_id": 20,
        "transaction_time": "2020-01-02T03:04:05-05:00",
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "transaction_time must be timezone-naive."


def test_score_accepts_zero_valued_entity_ids():
    scorer = FakeScoringService()
    client = TestClient(create_app(scoring_service=scorer))
    response = client.post("/score", json={
        "amount": 20,
        "client_id": 0,
        "card_id": 0,
        "merchant_id": 0,
        "transaction_time": "2020-01-02T03:04:05",
    })
    assert response.status_code == 200
    assert scorer.calls[0]["client_id"] == 0
    assert scorer.calls[0]["card_id"] == 0
    assert scorer.calls[0]["merchant_id"] == 0


def test_score_rejects_extra_fields():
    client = TestClient(create_app(scoring_service=FakeScoringService()))
    response = client.post("/score", json={
        "amount": 20,
        "client_id": 1,
        "card_id": 10,
        "merchant_id": 20,
        "transaction_time": "2020-01-02T03:04:05",
        "unexpected": "ignored fields are not accepted",
    })
    assert response.status_code == 422
