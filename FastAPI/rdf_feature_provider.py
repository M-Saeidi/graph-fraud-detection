"""Local RDF feature provider for small fixtures and compatibility checks.

The caller supplies an already-loaded graph. This module does not load URLs,
credentials, environment configuration, or data files, and is not a production
replacement for a persistent SPARQL server.
"""

from __future__ import annotations

import re

from rdflib import Graph

from graph_queries import build_a0_query, build_b1_state_query, build_c1_features_query


class RdfFeatureProvider:
    def __init__(self, graph: Graph):
        self.graph = graph

    def _one_row(self, query: str, family: str) -> dict[str, str]:
        rows = list(self.graph.query(query))
        if len(rows) != 1:
            raise RuntimeError(f"{family} cardinality invariant violated: expected one row.")
        return {str(name): str(value) for name, value in rows[0].asdict().items()}

    @staticmethod
    def _parse_money(value: str) -> float:
        cleaned = re.sub(r"[^0-9.\-]", "", value)
        if not cleaned:
            raise ValueError("Cannot parse money value.")
        return float(cleaned)

    def get_a0(self, *, client_id: int, card_id: int) -> dict[str, int | float]:
        row = self._one_row(build_a0_query(client_id=client_id, card_id=card_id), "A0")
        return {
            "currentAge": int(row["currentAge"]),
            "creditScore": int(row["creditScore"]),
            "yearlyIncome": self._parse_money(row["yearlyIncome"]),
            "creditLimit": self._parse_money(row["creditLimit"]),
        }

    def get_b1_state(self, *, card_id: int, scoring_time_key: int) -> dict[str, int | float | None]:
        row = self._one_row(build_b1_state_query(card_id=card_id, scoring_time_key=scoring_time_key), "B1")
        prior_count = int(float(row.get("prior_count") or 0))
        return {
            "prior_count": prior_count,
            "prior_avg_amount": float(row["prior_avg_amount"]) if prior_count else None,
            "previous_transaction_time_key": int(float(row["previous_transaction_time_key"])) if prior_count else None,
        }

    def get_c1_features(self, *, merchant_id: int, scoring_time_key: int) -> dict[str, int | float]:
        row = self._one_row(build_c1_features_query(merchant_id=merchant_id, scoring_time_key=scoring_time_key), "C1")
        features = {
            "merchant_prior_txn_count": int(float(row.get("merchant_prior_txn_count") or 0)),
            "merchant_prior_fraud_count": int(float(row.get("merchant_prior_fraud_count") or 0)),
            "merchant_prior_fraud_rate_pct": float(row.get("merchant_prior_fraud_rate_pct") or 0),
            "merchant_prior_unique_cards": int(float(row.get("merchant_prior_unique_cards") or 0)),
            "merchant_prior_unique_fraud_cards": int(float(row.get("merchant_prior_unique_fraud_cards") or 0)),
            "merchant_prior_fraud_card_ratio_pct": float(row.get("merchant_prior_fraud_card_ratio_pct") or 0),
        }
        if features["merchant_prior_fraud_count"] > features["merchant_prior_txn_count"]:
            raise RuntimeError("Invalid C1 state: fraud transaction count exceeds total transaction count.")
        if features["merchant_prior_unique_fraud_cards"] > features["merchant_prior_unique_cards"]:
            raise RuntimeError("Invalid C1 state: fraud-card count exceeds total unique-card count.")
        if not 0.0 <= features["merchant_prior_fraud_rate_pct"] <= 100.0:
            raise RuntimeError("Invalid C1 state: merchant fraud rate is outside [0, 100].")
        if not 0.0 <= features["merchant_prior_fraud_card_ratio_pct"] <= 100.0:
            raise RuntimeError("Invalid C1 state: merchant fraud-card ratio is outside [0, 100].")
        return features