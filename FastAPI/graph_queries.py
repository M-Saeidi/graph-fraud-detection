"""Read-only SPARQL feature queries using public, implementation-neutral IRIs."""

from __future__ import annotations


FRAUD_LABEL_LAG_SECONDS = 604800


def build_a0_query(*, client_id: int, card_id: int) -> str:
    """Retain the independent customer/card lookups used by the feature contract."""
    return f"""
PREFIX usr: <https://example.org/fraud/users#>
PREFIX card: <https://example.org/fraud/cards#>
SELECT ?currentAge ?creditScore ?yearlyIncome ?creditLimit
WHERE {{
    ?user usr:UsersData.id ?userId ;
        usr:UsersData.currentAge ?currentAge ;
        usr:UsersData.creditScore ?creditScore ;
        usr:UsersData.yearlyIncome ?yearlyIncome .
    FILTER(STR(?userId) = "{int(client_id)}")
    ?cardEntity card:CardsData.id ?cardId ;
        card:CardsData.creditLimit ?creditLimit .
    FILTER(STR(?cardId) = "{int(card_id)}")
}}
"""


def build_b1_state_query(*, card_id: int, scoring_time_key: int) -> str:
    """Retain labeled-population membership and strict earlier-time filtering."""
    return f"""
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX tx: <https://example.org/fraud/transactions#>
PREFIX feat: <https://example.org/fraud/features#>

SELECT
    (COUNT(DISTINCT ?priorTransactionId) AS ?prior_count)
    (AVG(?priorAmount) AS ?prior_avg_amount)
    (MAX(?priorTimeKey) AS ?previous_transaction_time_key)
WHERE {{
    ?priorTransaction
        tx:TransactionsData.cardId ?priorCardId ;
        tx:TransactionsData.id ?priorTransactionId ;
        tx:TransactionsData.amount ?priorAmountRaw ;
        feat:transactionTimeKey ?priorTimeKey ;
        feat:isFraud ?populationMembership .
    FILTER(STR(?priorCardId) = "{int(card_id)}")
    FILTER(xsd:integer(?priorTimeKey) < xsd:integer("{int(scoring_time_key)}"))
    BIND(xsd:double(REPLACE(STR(?priorAmountRaw), "[^0-9.-]", "")) AS ?priorAmount)
}}
"""


def build_c1_features_query(*, merchant_id: int, scoring_time_key: int) -> str:
    """Keep the eligible population while avoiding error-valued aggregates.

    Filtered subqueries replace conditional COUNT expressions that use a
    division-by-zero sentinel, whose handling differs between RDF engines.
    """
    population = f"""
    ?priorTransaction tx:TransactionsData.merchantId ?priorMerchantId ;
        tx:TransactionsData.id ?priorTransactionId ;
        feat:transactionTimeKey ?priorTimeKey ;
        feat:isFraud ?priorIsFraud .
    OPTIONAL {{ ?priorTransaction tx:TransactionsData.cardId ?priorCardId . }}
    FILTER(STR(?priorMerchantId) = "{int(merchant_id)}")
    FILTER((xsd:decimal("{int(scoring_time_key)}") - xsd:decimal(?priorTimeKey)) >= {FRAUD_LABEL_LAG_SECONDS})
"""
    return f"""
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX tx: <https://example.org/fraud/transactions#>
PREFIX feat: <https://example.org/fraud/features#>
SELECT
    ?merchant_prior_txn_count
    ?merchant_prior_fraud_count
    (IF(?merchant_prior_txn_count > 0,
        100.0 * xsd:decimal(?merchant_prior_fraud_count) / xsd:decimal(?merchant_prior_txn_count),
        0.0) AS ?merchant_prior_fraud_rate_pct)
    ?merchant_prior_unique_cards
    ?merchant_prior_unique_fraud_cards
    (IF(?merchant_prior_unique_cards > 0,
        100.0 * xsd:decimal(?merchant_prior_unique_fraud_cards) / xsd:decimal(?merchant_prior_unique_cards),
        0.0) AS ?merchant_prior_fraud_card_ratio_pct)
WHERE {{
    {{ SELECT
        (COUNT(DISTINCT ?priorTransactionId) AS ?merchant_prior_txn_count)
        (COUNT(DISTINCT ?priorCardId) AS ?merchant_prior_unique_cards)
        WHERE {{ {population} }}
    }}
    {{ SELECT
        (COUNT(DISTINCT ?priorTransactionId) AS ?merchant_prior_fraud_count)
        (COUNT(DISTINCT ?priorCardId) AS ?merchant_prior_unique_fraud_cards)
        WHERE {{ {population} FILTER(?priorIsFraud = true) }}
    }}
}}
"""