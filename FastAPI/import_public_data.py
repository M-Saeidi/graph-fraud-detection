"""Import a bounded, partial-history sample of the public transaction dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import islice
from pathlib import Path

import ijson
from rdflib import Graph, Literal, Namespace, RDF, XSD

from time_key import datetime_to_transaction_time_key


USER = Namespace("https://example.org/fraud/users#")
CARD = Namespace("https://example.org/fraud/cards#")
TRANSACTION = Namespace("https://example.org/fraud/transactions#")
FEATURE = Namespace("https://example.org/fraud/features#")
RESOURCE = Namespace("https://example.org/fraud/data/")
MAX_TRANSACTIONS = 10_000
HEADERS = {
    "transactions_data.csv": {"id", "date", "client_id", "card_id", "merchant_id", "amount"},
    "users_data.csv": {"id", "current_age", "credit_score", "yearly_income"},
    "cards_data.csv": {"id", "client_id", "credit_limit"},
}


@dataclass(frozen=True)
class Transaction:
    identifier: int
    client_id: int
    card_id: int
    merchant_id: int
    amount: Decimal
    time_key: int


@dataclass(frozen=True)
class ImportResult:
    graph: Graph
    manifest: dict


def _integer(value: str, field: str) -> int:
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value) is None:
        raise ValueError(f"Invalid integer in {field}.")
    return int(value)


def _money(value: str, field: str) -> Decimal:
    if re.fullmatch(r"\$?-?[0-9]+(?:\.[0-9]{1,2})?", value) is None:
        raise ValueError(f"Invalid money in {field}.")
    amount = Decimal(value.removeprefix("$"))
    if not math.isfinite(float(amount)):
        raise ValueError(f"Non-finite money in {field}.")
    return amount


def _rows(source: Path, filename: str):
    with (source / filename).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not HEADERS[filename].issubset(headers):
            raise ValueError(f"Missing or duplicate headers in {filename}.")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed row in {filename}.")
            yield {field: row[field] for field in HEADERS[filename]}


def _transactions(source: Path, limit: int) -> dict[int, Transaction]:
    transactions = {}
    for row in islice(_rows(source, "transactions_data.csv"), limit):
        identifier = _integer(row["id"], "transaction.id")
        if identifier in transactions:
            raise ValueError("Duplicate selected transaction ID.")
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", row["date"]) is None:
            raise ValueError("Invalid transaction timestamp format.")
        timestamp = datetime.strptime(row["date"], "%Y-%m-%d %H:%M:%S")
        transactions[identifier] = Transaction(
            identifier=identifier,
            client_id=_integer(row["client_id"], "transaction.client_id"),
            card_id=_integer(row["card_id"], "transaction.card_id"),
            merchant_id=_integer(row["merchant_id"], "transaction.merchant_id"),
            amount=_money(row["amount"], "transaction.amount"),
            time_key=datetime_to_transaction_time_key(timestamp),
        )
    if not transactions:
        raise ValueError("No transactions selected.")
    return transactions


def _labels(source: Path, selected: set[int]) -> dict[int, bool]:
    labels = {}
    with (source / "train_fraud_labels.json").open("rb") as stream:
        events = iter(ijson.parse(stream))
        expected = [("", "start_map", None), ("", "map_key", "target"), ("target", "start_map", None)]
        for event in expected:
            if next(events, None) != event:
                raise ValueError("Labels must contain exactly one target object.")
        for prefix, event, value in events:
            if (prefix, event) == ("target", "end_map"):
                break
            if (prefix, event) != ("target", "map_key"):
                raise ValueError("Invalid label mapping.")
            identifier = _integer(value, "label transaction ID")
            label_prefix, label_event, label = next(events, (None, None, None))
            if label_prefix != f"target.{value}" or label_event != "string" or label not in {"Yes", "No"}:
                raise ValueError("Labels must be Yes or No strings.")
            if identifier in selected:
                if identifier in labels:
                    raise ValueError("Duplicate label for a selected transaction.")
                labels[identifier] = label == "Yes"
        else:
            raise ValueError("Incomplete label mapping.")
        if next(events, None) != ("", "end_map", None) or next(events, None) is not None:
            raise ValueError("Unexpected content after target labels.")
    return labels


def _add_entities(graph: Graph, source: Path, transactions: dict[int, Transaction]) -> tuple[int, int]:
    clients = {transaction.client_id for transaction in transactions.values()}
    card_owners = {}
    for transaction in transactions.values():
        if card_owners.setdefault(transaction.card_id, transaction.client_id) != transaction.client_id:
            raise ValueError("Selected transactions disagree on card ownership.")
    found_clients = set()
    for row in _rows(source, "users_data.csv"):
        identifier = _integer(row["id"], "user.id")
        if identifier not in clients:
            continue
        if identifier in found_clients:
            raise ValueError("Duplicate referenced user ID.")
        found_clients.add(identifier)
        subject = RESOURCE[f"users/{identifier}"]
        graph.add((subject, RDF.type, USER.User))
        graph.add((subject, USER["UsersData.id"], Literal(identifier)))
        for column, predicate in [("current_age", "currentAge"), ("credit_score", "creditScore")]:
            graph.add((subject, USER[f"UsersData.{predicate}"], Literal(_integer(row[column], column))))
        graph.add((subject, USER["UsersData.yearlyIncome"], Literal(_money(row["yearly_income"], "yearly_income"))))
    found_cards = set()
    for row in _rows(source, "cards_data.csv"):
        identifier = _integer(row["id"], "card.id")
        if identifier not in card_owners:
            continue
        if identifier in found_cards:
            raise ValueError("Duplicate referenced card ID.")
        if _integer(row["client_id"], "card.client_id") != card_owners[identifier]:
            raise ValueError("Referenced card ownership mismatch.")
        found_cards.add(identifier)
        subject = RESOURCE[f"cards/{identifier}"]
        graph.add((subject, RDF.type, CARD.Card))
        graph.add((subject, CARD["CardsData.id"], Literal(identifier)))
        graph.add((subject, CARD["CardsData.creditLimit"], Literal(_money(row["credit_limit"], "credit_limit"))))
    if found_clients != clients or found_cards != set(card_owners):
        raise ValueError("Missing referenced user or card.")
    return len(found_clients), len(found_cards)


def _fingerprints(source: Path) -> dict:
    fingerprints = {}
    for filename in [*HEADERS, "train_fraud_labels.json"]:
        with (source / filename).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        fingerprints[filename] = {"sha256": digest, "bytes": (source / filename).stat().st_size}
    return fingerprints


def serialize_graph(graph: Graph) -> bytes:
    """Return stable N-Triples bytes for this blank-node-free import graph."""
    return ("\n".join(sorted(graph.serialize(format="nt").splitlines())) + "\n").encode("utf-8")


def import_sample(source: Path, *, limit: int) -> ImportResult:
    """Select the first N CSV rows; stream labels and retain only referenced entities."""
    if type(limit) is not int or not 1 <= limit <= MAX_TRANSACTIONS:
        raise ValueError(f"limit must be an integer from 1 to {MAX_TRANSACTIONS}.")
    fingerprints = _fingerprints(source)
    transactions = _transactions(source, limit)
    labels = _labels(source, set(transactions))
    graph = Graph()
    user_count, card_count = _add_entities(graph, source, transactions)
    for transaction in transactions.values():
        subject = RESOURCE[f"transactions/{transaction.identifier}"]
        graph.add((subject, RDF.type, TRANSACTION.Transaction))
        for field, value in [("id", transaction.identifier), ("cardId", transaction.card_id), ("merchantId", transaction.merchant_id)]:
            graph.add((subject, TRANSACTION[f"TransactionsData.{field}"], Literal(value, datatype=XSD.integer)))
        graph.add((subject, TRANSACTION["TransactionsData.amount"], Literal(transaction.amount)))
        graph.add((subject, FEATURE.transactionTimeKey, Literal(transaction.time_key, datatype=XSD.integer)))
        if transaction.identifier in labels:
            graph.add((subject, FEATURE.isFraud, Literal(labels[transaction.identifier], datatype=XSD.boolean)))
    if _fingerprints(source) != fingerprints:
        raise ValueError("Input files changed during import; retry with immutable inputs.")
    manifest = {
        "format_version": 1,
        "dataset_url": "https://www.kaggle.com/datasets/computingvictor/transactions-fraud-datasets",
        "reference_dataset_version": 1,
        "source_verification": "local files; not authenticated against publisher checksums",
        "selection": {"strategy": "first_csv_rows", "limit": limit, "partial_history": True},
        "inputs": fingerprints,
        "counts": {"transactions": len(transactions), "users": user_count, "cards": card_count,
                   "labeled": len(labels), "fraud": sum(labels.values()), "triples": len(graph)},
        "time_key_range": {"minimum": min(transaction.time_key for transaction in transactions.values()),
                           "maximum": max(transaction.time_key for transaction in transactions.values())},
        "rdf_sha256": hashlib.sha256(serialize_graph(graph)).hexdigest(),
    }
    return ImportResult(graph, manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--limit", required=True, type=int)
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "local-data" / f"rdf-first-{args.limit}"
    if output.exists():
        parser.error("Sample output already exists; refusing to overwrite it.")
    result = import_sample(args.input_dir, limit=args.limit)
    output.mkdir(parents=True, exist_ok=False)
    (output / "sample.nt").write_bytes(serialize_graph(result.graph))
    (output / "manifest.json").write_text(json.dumps(result.manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": f"local-data/{output.name}", "counts": result.manifest["counts"]}, sort_keys=True))


if __name__ == "__main__":
    main()