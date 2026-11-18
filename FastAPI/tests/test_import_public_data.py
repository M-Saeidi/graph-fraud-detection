"""Test the CSV/JSON boundary with generated fixtures, never bundled source data."""

import csv
import hashlib
import json
from datetime import datetime

import pytest
from ijson import JSONError
from rdflib import Graph, RDF, XSD

import import_public_data
from feature_assembler import as_ordered_row, assemble_c1_features, calculate_b1
from import_public_data import CARD, FEATURE, RESOURCE, TRANSACTION, USER, import_sample, serialize_graph
from rdf_feature_provider import RdfFeatureProvider
from time_key import datetime_to_transaction_time_key


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def source(tmp_path):
    write_csv(tmp_path / "transactions_data.csv", [
        {"id": 1, "date": "2020-01-01 00:00:00", "client_id": 1, "card_id": 10, "merchant_id": 20, "amount": "$10", "errors": "unused"},
        {"id": 2, "date": "2020-01-02 00:00:00", "client_id": 1, "card_id": 10, "merchant_id": 20, "amount": "$30", "errors": "unused"},
        {"id": 3, "date": "2020-01-03 00:00:00", "client_id": 1, "card_id": 10, "merchant_id": 20, "amount": "$900", "errors": "unused"},
    ])
    write_csv(tmp_path / "users_data.csv", [
        {"id": 1, "current_age": 35, "credit_score": 650, "yearly_income": "$60000", "address": "DO_NOT_EXPORT"},
        {"id": 2, "current_age": 40, "credit_score": 700, "yearly_income": "$90000", "address": "DO_NOT_EXPORT"},
    ])
    write_csv(tmp_path / "cards_data.csv", [
        {"id": 10, "client_id": 1, "credit_limit": "$5000", "cvv": "DO_NOT_EXPORT", "card_number": "DO_NOT_EXPORT"},
        {"id": 11, "client_id": 2, "credit_limit": "$6000", "cvv": "DO_NOT_EXPORT", "card_number": "DO_NOT_EXPORT"},
    ])
    (tmp_path / "train_fraud_labels.json").write_text(json.dumps({"target": {"1": "No", "2": "Yes", "99": "No"}}), encoding="utf-8")
    return tmp_path


def rewrite_csv(source, filename, change):
    with (source / filename).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    change(rows)
    write_csv(source / filename, rows)


def test_import_to_exact_feature_row_and_allowed_vocabulary(source):
    result = import_sample(source, limit=3)
    provider = RdfFeatureProvider(result.graph)
    cutoff = datetime_to_transaction_time_key(datetime(2020, 1, 9))
    features = assemble_c1_features(
        amount=60,
        a0=provider.get_a0(client_id=1, card_id=10),
        b1=calculate_b1(amount=60, scoring_time_key=cutoff, b1_state=provider.get_b1_state(card_id=10, scoring_time_key=cutoff)),
        c1=provider.get_c1_features(merchant_id=20, scoring_time_key=cutoff),
    )
    assert as_ordered_row(features) == [60, 60000, 5000, 35, 650, 2, 20, 3, 168, 2, 1, 50, 1, 1, 100]
    assert result.graph.value(RESOURCE["transactions/1"], FEATURE.isFraud).toPython() is False
    assert result.graph.value(RESOURCE["transactions/2"], FEATURE.isFraud).toPython() is True
    assert result.graph.value(RESOURCE["transactions/3"], FEATURE.isFraud) is None
    assert result.graph.value(RESOURCE["transactions/1"], FEATURE.transactionTimeKey).datatype == XSD.integer
    assert set(result.graph.predicates()) == {
        RDF.type, USER["UsersData.id"], USER["UsersData.currentAge"], USER["UsersData.creditScore"], USER["UsersData.yearlyIncome"],
        CARD["CardsData.id"], CARD["CardsData.creditLimit"], TRANSACTION["TransactionsData.id"],
        TRANSACTION["TransactionsData.cardId"], TRANSACTION["TransactionsData.merchantId"], TRANSACTION["TransactionsData.amount"],
        FEATURE.transactionTimeKey, FEATURE.isFraud,
    }
    assert result.manifest["counts"] == {"transactions": 3, "users": 1, "cards": 1, "labeled": 2, "fraud": 1, "triples": 28}
    assert b"DO_NOT_EXPORT" not in serialize_graph(result.graph)


def test_repeatable_bounded_import_and_fingerprints(source):
    first = import_sample(source, limit=1)
    second = import_sample(source, limit=1)
    assert first.manifest == second.manifest
    assert serialize_graph(first.graph) == serialize_graph(second.graph)
    assert len(list(first.graph.subjects(RDF.type, TRANSACTION.Transaction))) == 1
    assert not list(first.graph.triples((RESOURCE["transactions/2"], None, None)))
    assert first.manifest["selection"] == {"strategy": "first_csv_rows", "limit": 1, "partial_history": True}
    for filename, fingerprint in first.manifest["inputs"].items():
        assert fingerprint["sha256"] == hashlib.sha256((source / filename).read_bytes()).hexdigest()
    assert first.manifest["rdf_sha256"] == hashlib.sha256(serialize_graph(first.graph)).hexdigest()
    assert str(source) not in json.dumps(first.manifest)
    parsed = Graph().parse(data=serialize_graph(first.graph), format="nt")
    assert set(parsed) == set(first.graph)


@pytest.mark.parametrize("limit", [0, -1, 10001, True, 1.5])
def test_invalid_limit(source, limit):
    with pytest.raises(ValueError, match="limit"):
        import_sample(source, limit=limit)


@pytest.mark.parametrize("column,value", [
    ("date", "2020-01-01T00:00:00Z"), ("date", "2020-02-30 00:00:00"),
    ("amount", "NaN"), ("amount", "$1oops"), ("amount", "1e309"), ("amount", "9" * 310),
    ("amount", "$1.001"), ("card_id", "10.0"), ("id", "01"),
])
def test_invalid_selected_transaction(source, column, value):
    rewrite_csv(source, "transactions_data.csv", lambda rows: rows[0].update({column: value}))
    with pytest.raises(ValueError):
        import_sample(source, limit=1)


@pytest.mark.parametrize("payload", [
    '{"target":{"1":true}}', '{"target":{"1":"unknown"}}', '{"target":{}} trailing',
    '{"other":{"1":"Yes"}}', '{"target":{"1":"Yes","1":"No"}}',
    '{"target":{"1":"No"},"extra":{}}', '{"target":{', '[]',
])
def test_invalid_labels(source, payload):
    (source / "train_fraud_labels.json").write_text(payload, encoding="utf-8")
    with pytest.raises((ValueError, JSONError)):
        import_sample(source, limit=1)


@pytest.mark.parametrize("filename", ["transactions_data.csv", "users_data.csv", "cards_data.csv"])
def test_duplicate_selected_identity(source, filename):
    rewrite_csv(source, filename, lambda rows: rows.insert(1, rows[0].copy()))
    with pytest.raises(ValueError, match="Duplicate"):
        import_sample(source, limit=3)


@pytest.mark.parametrize("filename", ["users_data.csv", "cards_data.csv"])
def test_missing_reference(source, filename):
    rewrite_csv(source, filename, lambda rows: rows.pop(0))
    with pytest.raises(ValueError, match="Missing referenced"):
        import_sample(source, limit=1)


def test_ownership_mismatch(source):
    rewrite_csv(source, "cards_data.csv", lambda rows: rows[0].update(client_id="2"))
    with pytest.raises(ValueError, match="ownership"):
        import_sample(source, limit=1)


def test_missing_required_header(source):
    rewrite_csv(source, "transactions_data.csv", lambda rows: [row.pop("amount") for row in rows])
    with pytest.raises(ValueError, match="headers"):
        import_sample(source, limit=1)


def test_missing_all_labels_and_negative_amount(source):
    (source / "train_fraud_labels.json").write_text('{"target":{}}', encoding="utf-8")
    rewrite_csv(source, "transactions_data.csv", lambda rows: rows[0].update(amount="$-10.25"))
    result = import_sample(source, limit=1)
    assert not list(result.graph.triples((None, FEATURE.isFraud, None)))
    assert float(result.graph.value(RESOURCE["transactions/1"], TRANSACTION["TransactionsData.amount"])) == -10.25
    assert RdfFeatureProvider(result.graph).get_b1_state(card_id=10, scoring_time_key=10**15)["prior_count"] == 0


def test_unselected_transactions_are_not_imported_or_validated(source):
    rewrite_csv(source, "transactions_data.csv", lambda rows: rows[1].update(amount="invalid"))
    assert import_sample(source, limit=1).manifest["counts"]["transactions"] == 1


def test_changed_input_is_rejected(source, monkeypatch):
    fingerprint = import_public_data._fingerprints(source)
    results = iter([fingerprint, {}])
    monkeypatch.setattr(import_public_data, "_fingerprints", lambda source: next(results))
    with pytest.raises(ValueError, match="changed during import"):
        import_sample(source, limit=1)


def test_cli_outputs_manifest_and_refuses_overwrite(source, monkeypatch, capsys):
    monkeypatch.setattr(import_public_data, "__file__", str(source / "FastAPI" / "import_public_data.py"))
    monkeypatch.setattr("sys.argv", ["import_public_data", "--input-dir", str(source), "--limit", "1"])
    import_public_data.main()
    output = source / "local-data" / "rdf-first-1"
    original = (output / "sample.nt").read_bytes()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["rdf_sha256"] == hashlib.sha256(original).hexdigest()
    assert json.loads(capsys.readouterr().out)["output"] == "local-data/rdf-first-1"
    with pytest.raises(SystemExit) as error:
        import_public_data.main()
    assert error.value.code == 2
    assert (output / "sample.nt").read_bytes() == original