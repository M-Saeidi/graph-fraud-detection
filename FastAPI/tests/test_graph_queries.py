"""Execute migrated queries over deliberately small, synthetic RDF graphs."""

from pathlib import Path

import pytest
from rdflib import Graph, Literal, RDF, RDFS, URIRef

from feature_assembler import as_ordered_row, assemble_c1_features, calculate_b1
from graph_queries import build_a0_query, build_b1_state_query, build_c1_features_query
from rdf_feature_provider import RdfFeatureProvider


PREFIXES = """
@prefix tx: <https://example.org/fraud/transactions#> .
@prefix feat: <https://example.org/fraud/features#> .
@prefix demo: <https://example.org/fraud/demo/> .
@prefix usr: <https://example.org/fraud/users#> .
@prefix card: <https://example.org/fraud/cards#> .
"""


@pytest.fixture
def card_history():
    return Graph().parse(data=PREFIXES + """
demo:first tx:TransactionsData.id 1 ; tx:TransactionsData.cardId 10 ;
    tx:TransactionsData.amount "$10" ; feat:transactionTimeKey 100 ; feat:isFraud false .
demo:second tx:TransactionsData.id 2 ; tx:TransactionsData.cardId 10 ;
    tx:TransactionsData.amount "$30" ; feat:transactionTimeKey 200 ; feat:isFraud true .
demo:unlabeled tx:TransactionsData.id 3 ; tx:TransactionsData.cardId 10 ;
    tx:TransactionsData.amount "$900" ; feat:transactionTimeKey 300 .
demo:equal tx:TransactionsData.id 4 ; tx:TransactionsData.cardId 10 ;
    tx:TransactionsData.amount "$900" ; feat:transactionTimeKey 400 ; feat:isFraud true .
demo:future tx:TransactionsData.id 5 ; tx:TransactionsData.cardId 10 ;
    tx:TransactionsData.amount "$900" ; feat:transactionTimeKey 500 ; feat:isFraud true .
demo:otherCard tx:TransactionsData.id 6 ; tx:TransactionsData.cardId 11 ;
    tx:TransactionsData.amount "$900" ; feat:transactionTimeKey 100 ; feat:isFraud true .
""", format="turtle")


def select_row(graph, query):
    rows = list(graph.query(query))
    assert len(rows) == 1
    return {str(name): value.toPython() for name, value in rows[0].asdict().items()}


def test_b1_preserves_labeled_population_and_strict_cutoff(card_history):
    row = select_row(card_history, build_b1_state_query(card_id=10, scoring_time_key=400))
    assert row == {"prior_count": 2, "prior_avg_amount": 20.0, "previous_transaction_time_key": 200}


@pytest.mark.parametrize("card_id,cutoff", [(99, 400), (10, 100)])
def test_b1_empty_history(card_history, card_id, cutoff):
    row = select_row(card_history, build_b1_state_query(card_id=card_id, scoring_time_key=cutoff))
    assert row["prior_count"] == 0
    assert row.get("previous_transaction_time_key") is None


def test_a0_attribute_lookup():
    graph = Graph().parse(data=PREFIXES + """
demo:user usr:UsersData.id 1 ; usr:UsersData.currentAge 35 ;
    usr:UsersData.creditScore 650 ; usr:UsersData.yearlyIncome "$60,000" .
demo:card card:CardsData.id 10 ; card:CardsData.creditLimit "$5,000" .
""", format="turtle")
    assert select_row(graph, build_a0_query(client_id=1, card_id=10)) == {
        "currentAge": 35, "creditScore": 650, "yearlyIncome": "$60,000", "creditLimit": "$5,000",
    }
    assert list(graph.query(build_a0_query(client_id=99, card_id=10))) == []


@pytest.fixture
def merchant_history():
    return Graph().parse(data=PREFIXES + """
demo:old tx:TransactionsData.id 101 ; tx:TransactionsData.merchantId 20 ;
    tx:TransactionsData.cardId 10 ; feat:transactionTimeKey 100000 ; feat:isFraud false .
demo:boundary tx:TransactionsData.id 102 ; tx:TransactionsData.merchantId 20 ;
    tx:TransactionsData.cardId 11 ; feat:transactionTimeKey 395200 ; feat:isFraud true .
demo:duplicateId tx:TransactionsData.id 102 ; tx:TransactionsData.merchantId 20 ;
    tx:TransactionsData.cardId 11 ; feat:transactionTimeKey 395200 ; feat:isFraud true .
demo:missingCard tx:TransactionsData.id 103 ; tx:TransactionsData.merchantId 20 ;
    feat:transactionTimeKey 300000 ; feat:isFraud true .
demo:recent tx:TransactionsData.id 104 ; tx:TransactionsData.merchantId 20 ;
    tx:TransactionsData.cardId 12 ; feat:transactionTimeKey 395201 ; feat:isFraud true .
demo:unlabeled tx:TransactionsData.id 105 ; tx:TransactionsData.merchantId 20 ;
    tx:TransactionsData.cardId 13 ; feat:transactionTimeKey 100000 .
demo:equal tx:TransactionsData.id 106 ; tx:TransactionsData.merchantId 20 ;
    tx:TransactionsData.cardId 14 ; feat:transactionTimeKey 1000000 ; feat:isFraud true .
demo:future tx:TransactionsData.id 107 ; tx:TransactionsData.merchantId 20 ;
    tx:TransactionsData.cardId 15 ; feat:transactionTimeKey 1000001 ; feat:isFraud false .
demo:otherMerchant tx:TransactionsData.id 108 ; tx:TransactionsData.merchantId 21 ;
    tx:TransactionsData.cardId 16 ; feat:transactionTimeKey 100000 ; feat:isFraud true .
demo:sharedCard tx:TransactionsData.id 109 ; tx:TransactionsData.merchantId 20 ;
    tx:TransactionsData.cardId 10 ; feat:transactionTimeKey 200000 ; feat:isFraud true .
""", format="turtle")


def test_c1_boundary_population_distinct_ids_and_optional_cards(merchant_history):
    row = select_row(merchant_history, build_c1_features_query(merchant_id=20, scoring_time_key=1_000_000))
    assert row == {
        "merchant_prior_txn_count": 4,
        "merchant_prior_fraud_count": 3,
        "merchant_prior_fraud_rate_pct": 75,
        "merchant_prior_unique_cards": 2,
        "merchant_prior_unique_fraud_cards": 2,
        "merchant_prior_fraud_card_ratio_pct": 100,
    }


def test_c1_zero_history(merchant_history):
    row = select_row(merchant_history, build_c1_features_query(merchant_id=99, scoring_time_key=1_000_000))
    assert len(row) == 6
    assert all(value == 0 for value in row.values())


def test_c1_no_card_identifiers_keeps_transaction_population(merchant_history):
    merchant_history.remove((None, URIRef("https://example.org/fraud/transactions#TransactionsData.cardId"), None))
    row = select_row(merchant_history, build_c1_features_query(merchant_id=20, scoring_time_key=1_000_000))
    assert row["merchant_prior_txn_count"] == 4
    assert row["merchant_prior_fraud_count"] == 3
    assert row["merchant_prior_unique_cards"] == 0
    assert row["merchant_prior_unique_fraud_cards"] == 0
    assert row["merchant_prior_fraud_card_ratio_pct"] == 0


@pytest.fixture
def pipeline_graph():
    return Graph().parse(data=PREFIXES + """
demo:user a usr:User ; usr:UsersData.id 1 ; usr:UsersData.currentAge 35 ;
    usr:UsersData.creditScore 650 ; usr:UsersData.yearlyIncome "$60,000" .
demo:card a card:Card ; card:CardsData.id 10 ; card:CardsData.creditLimit "$5,000" .
demo:first a tx:Transaction ; tx:TransactionsData.id 1 ; tx:TransactionsData.cardId 10 ;
    tx:TransactionsData.merchantId 20 ; tx:TransactionsData.amount "$10" ;
    feat:transactionTimeKey 395199 ; feat:isFraud false .
demo:second a tx:Transaction ; tx:TransactionsData.id 2 ; tx:TransactionsData.cardId 10 ;
    tx:TransactionsData.merchantId 20 ; tx:TransactionsData.amount "$30" ;
    feat:transactionTimeKey 395200 ; feat:isFraud true .
""", format="turtle")


def test_rdf_queries_feed_existing_15_feature_assembler(pipeline_graph):
    provider = RdfFeatureProvider(pipeline_graph)
    features = assemble_c1_features(
        amount=60.0,
        a0=provider.get_a0(client_id=1, card_id=10),
        b1=calculate_b1(amount=60.0, scoring_time_key=1_000_000,
                        b1_state=provider.get_b1_state(card_id=10, scoring_time_key=1_000_000)),
        c1=provider.get_c1_features(merchant_id=20, scoring_time_key=1_000_000),
    )
    assert as_ordered_row(features) == [60.0, 60000.0, 5000.0, 35, 650, 2, 20.0, 3.0, 168.0, 2, 1, 50.0, 1, 1, 100.0]


def test_provider_normalizes_empty_history(pipeline_graph):
    provider = RdfFeatureProvider(pipeline_graph)
    assert provider.get_b1_state(card_id=99, scoring_time_key=1_000_000) == {
        "prior_count": 0, "prior_avg_amount": None, "previous_transaction_time_key": None,
    }
    assert all(value == 0 for value in provider.get_c1_features(merchant_id=99, scoring_time_key=1_000_000).values())


def test_provider_rejects_missing_or_ambiguous_a0(pipeline_graph):
    provider = RdfFeatureProvider(pipeline_graph)
    with pytest.raises(RuntimeError, match="A0 cardinality"):
        provider.get_a0(client_id=99, card_id=10)
    pipeline_graph.add((URIRef("https://example.org/fraud/demo/user"),
                        URIRef("https://example.org/fraud/users#UsersData.creditScore"), Literal(700)))
    with pytest.raises(RuntimeError, match="A0 cardinality"):
        provider.get_a0(client_id=1, card_id=10)


def test_schema_declares_fixture_predicates_and_classes(pipeline_graph):
    schema_path = Path(__file__).resolve().parents[2] / "graph" / "schema.ttl"
    schema = Graph().parse(schema_path, format="turtle")
    for predicate in set(pipeline_graph.predicates()) - {RDF.type}:
        assert (predicate, RDF.type, RDF.Property) in schema
    for class_name in set(pipeline_graph.objects(None, RDF.type)):
        assert (class_name, RDF.type, RDFS.Class) in schema


def test_b1_duplicate_ids_preserve_solution_weighted_average(card_history):
    card_history.parse(data=PREFIXES + """
demo:duplicate tx:TransactionsData.id 2 ; tx:TransactionsData.cardId 10 ;
    tx:TransactionsData.amount "$30" ; feat:transactionTimeKey 200 ; feat:isFraud true .
""", format="turtle")
    row = select_row(card_history, build_b1_state_query(card_id=10, scoring_time_key=400))
    assert row["prior_count"] == 2
    assert row["prior_avg_amount"] == pytest.approx(70 / 3)


def test_c1_all_false_labels_are_not_counted_as_fraud(merchant_history):
    predicate = URIRef("https://example.org/fraud/features#isFraud")
    for subject in list(merchant_history.subjects(predicate, None)):
        merchant_history.set((subject, predicate, Literal(False)))
    row = select_row(merchant_history, build_c1_features_query(merchant_id=20, scoring_time_key=1_000_000))
    assert row["merchant_prior_txn_count"] == 4
    assert row["merchant_prior_fraud_count"] == 0
    assert row["merchant_prior_unique_fraud_cards"] == 0


@pytest.mark.parametrize("builder,parameters", [
    (build_a0_query, {"client_id": "invalid", "card_id": 10}),
    (build_b1_state_query, {"card_id": "invalid", "scoring_time_key": 100}),
    (build_c1_features_query, {"merchant_id": "invalid", "scoring_time_key": 100}),
])
def test_query_parameters_require_integer_conversion(builder, parameters):
    with pytest.raises(ValueError):
        builder(**parameters)