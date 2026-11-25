"""Loopback-only FastAPI adapter for the local portfolio scoring demo."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from rdflib import Graph, Namespace

from local_inference import LocalInferenceError, XGBoostInferenceProvider
from local_scoring_service import LocalFraudScoringService
from graph_queries import FRAUD_LABEL_LAG_SECONDS
from rdf_feature_provider import RdfFeatureProvider
from time_key import datetime_to_transaction_time_key, transaction_time_key_to_datetime


PARITY_STATUS = "not_exactly_equivalent_to_ai_studio"
USER = Namespace("https://example.org/fraud/users#")
CARD = Namespace("https://example.org/fraud/cards#")
TRANSACTION = Namespace("https://example.org/fraud/transactions#")
FEATURE = Namespace("https://example.org/fraud/features#")


class ScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: float = Field(allow_inf_nan=False)
    client_id: int = Field(strict=True, ge=0)
    card_id: int = Field(strict=True, ge=0)
    merchant_id: int = Field(strict=True, ge=0)
    transaction_time: datetime


class ScoreResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction: bool
    fraud_confidence: float = Field(ge=0.0, le=1.0)
    non_fraud_confidence: float = Field(ge=0.0, le=1.0)
    evidence: dict[str, int | float]
    timings_ms: dict[str, float]
    model_parity: Literal["not_exactly_equivalent_to_ai_studio"]


class DemoDefaultsResponse(BaseModel):
    amount: float
    client_id: int
    card_id: int
    merchant_id: int
    transaction_time: str


def _build_local_service() -> LocalFraudScoringService:
    project_root = Path(__file__).resolve().parents[1]
    graph_path = Path(os.environ.get(
        "FRAUD_GRAPH_FILE",
        project_root / "graph" / "demo-data.ttl",
    )).expanduser()
    model_path = Path(os.environ.get(
        "FRAUD_MODEL_FILE",
        project_root / "models" / "c1_fraud_model.json",
    )).expanduser()

    if not graph_path.is_file() or not model_path.is_file():
        raise RuntimeError(
            "Local demo artifacts are missing. Set FRAUD_GRAPH_FILE and "
            "FRAUD_MODEL_FILE to local files before starting the API."
        )

    graph_format = {".nt": "nt", ".ttl": "turtle"}.get(graph_path.suffix.lower())
    if graph_format is None:
        raise RuntimeError("FRAUD_GRAPH_FILE must reference an .nt or .ttl file.")

    graph = Graph()
    try:
        graph.parse(location=str(graph_path), format=graph_format)
    except Exception as exc:
        raise RuntimeError("Could not load the configured local RDF graph.") from exc

    feature_provider = RdfFeatureProvider(graph)
    inference_provider = XGBoostInferenceProvider(
        model_path=model_path,
        fraud_threshold=0.5,
        native_probability_is_fraud=True,
    )
    return LocalFraudScoringService(
        feature_provider=feature_provider,
        inference_provider=inference_provider,
    )


def create_app(*, scoring_service: Any | None = None) -> FastAPI:
    """Create the API; inject a scorer for tests or load local files for demo use."""
    service = scoring_service if scoring_service is not None else _build_local_service()
    app = FastAPI(
        title="Graph Fraud Scoring Demo",
        version="0.1.0",
        description=(
            "Local portfolio demonstration. Native XGBoost output is not an "
            "exact reproduction of the original AI Studio scorer."
        ),
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "model_parity": PARITY_STATUS}

    @app.get("/demo-defaults", response_model=DemoDefaultsResponse)
    def demo_defaults() -> dict[str, Any]:
        feature_provider = getattr(service, "feature_provider", None)
        graph = getattr(feature_provider, "graph", None)
        if not isinstance(graph, Graph):
            raise HTTPException(
                status_code=503,
                detail="Local graph defaults are unavailable.",
            )

        def first_id(predicate: Any) -> int:
            for value in graph.objects(None, predicate):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
            raise HTTPException(
                status_code=503,
                detail="Local graph defaults are unavailable.",
            )

        merchant_id = first_id(TRANSACTION["TransactionsData.merchantId"])
        graph_times = [
            int(value)
            for value in graph.objects(None, FEATURE.transactionTimeKey)
            if str(value).lstrip("-").isdigit()
        ]
        example_time = (
            transaction_time_key_to_datetime(max(graph_times) + FRAUD_LABEL_LAG_SECONDS)
            if graph_times
            else datetime.now().replace(microsecond=0)
        )
        return {
            "amount": 75.0,
            "client_id": first_id(USER["UsersData.id"]),
            "card_id": first_id(CARD["CardsData.id"]),
            "merchant_id": merchant_id,
            "transaction_time": example_time.isoformat(),
        }

    @app.post("/score", response_model=ScoreResponse)
    def score(request: ScoreRequest) -> dict[str, Any]:
        try:
            time_key = datetime_to_transaction_time_key(request.transaction_time)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="transaction_time must be timezone-naive.",
            ) from exc

        try:
            result = service.score_transaction(
                amount=request.amount,
                client_id=request.client_id,
                card_id=request.card_id,
                merchant_id=request.merchant_id,
                scoring_time_key=time_key,
            )
        except LocalInferenceError as exc:
            raise HTTPException(
                status_code=503,
                detail="Local model inference is unavailable.",
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Feature generation failed for the supplied entities or time.",
            ) from exc
        return result

    return app
