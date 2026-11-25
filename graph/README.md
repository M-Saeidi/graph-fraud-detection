# RDF Feature Model and Import

This guide describes the local graph model used to retrieve A0/B1/C1 features.
RDFLib runs the SPARQL queries against an in-memory graph for the scoring
prototype and small fixtures. It is not a persistent graph service; Apache Jena
Fuseki has not been installed or tested.

## Vocabulary versus data

[schema.ttl](schema.ttl) defines a minimal, task-specific RDFS vocabulary for
the customer, card, transaction, and feature values used by this scoring path.
It uses reserved example namespaces and does not claim to model every concept
in a banking or fraud domain.

The vocabulary describes customer, card, and transaction resources. Card and
merchant references are numeric ID literals in this feature contract. A0 uses
independent customer/card lookups and does not verify ownership.

| Logical field | Predicate | Mapping contract |
| --- | --- | --- |
| Customer ID | usr:UsersData.id | Canonical integer |
| Age / credit score | usr:UsersData.currentAge / usr:UsersData.creditScore | Integer attributes |
| Yearly income | usr:UsersData.yearlyIncome | Money lexical value normalized by the provider |
| Card ID / limit | card:CardsData.id / card:CardsData.creditLimit | Integer / money lexical value |
| Transaction ID | tx:TransactionsData.id | Canonical integer |
| Card / merchant reference | tx:TransactionsData.cardId / tx:TransactionsData.merchantId | Integer IDs; missing cards are not fabricated |
| Amount | tx:TransactionsData.amount | Money lexical value normalized in SPARQL |
| Time key | feat:transactionTimeKey | Custom day-based integer scale in seconds, not Unix time |
| Fraud label | feat:isFraud | RDF boolean only when a label is present; absence is not false |

Prefix IRIs are declared in the schema. They are identifiers, not services to
call. RDFS domain/range declarations describe meaning; they do not enforce
constraints. The importer validates selected identities, required references,
and value encodings. SHACL validation and complete ontology comparison remain
future work. No reasoning is required here.

The importer accepts a caller-provided local dataset directory. The previously
used local-file prefix has not been authenticated against the publisher; no raw
files are distributed. Hand-authored Turtle fixtures in
[the query tests](../FastAPI/tests/test_graph_queries.py) test known expected
results, not real-world accuracy or source-data provenance.

## Bounded import

[The importer](../FastAPI/import_public_data.py) selects the first N data rows in
CSV order, with an explicit limit from 1 to 10,000. It does not shuffle, sort,
balance classes, or reconstruct complete history. It loads only users/cards
referenced by that prefix and streams the entire fraud-label mapping while
retaining only selected labels. Unselected transactions are not validated.

The importer reads the following fields from the caller-provided files. The
Kaggle page confirms a version and file set, not the byte identity of the local
files.

| Input | Selected columns | RDF mapping |
| --- | --- | --- |
| transactions_data.csv | id, card_id, merchant_id, amount | Corresponding TransactionsData predicates above; integers and xsd:decimal money |
| transactions_data.csv | date | Exact naive YYYY-MM-DD HH:MM:SS, converted by `time_key.py` |
| transactions_data.csv | client_id | Reference/ownership validation only; not emitted |
| users_data.csv | id, current_age, credit_score, yearly_income | Corresponding UsersData predicates; integers and xsd:decimal money |
| cards_data.csv | id, credit_limit | Corresponding CardsData predicates; integer and xsd:decimal money |
| cards_data.csv | client_id | Ownership validation only; not emitted |
| train_fraud_labels.json | target object mapping transaction ID strings to Yes/No strings | Yes becomes true, No becomes false; a missing key emits no label |

All other columns are discarded. No card numbers, CVVs, addresses, coordinates,
merchant-location fields, error text, or unrelated JSON files enter the graph.
Money accepts an optional dollar prefix, optional minus sign, and at most two
decimal places, with no grouping separators or exponent notation; non-finite
values are rejected. IDs use canonical signed integer strings. Selected duplicate
IDs, missing references, malformed labels, and card-owner disagreement fail
the import rather than silently merge records. Duplicate unselected label IDs
are not tracked. Ownership validation does not change A0's independent lookups.

Resources use stable public identifiers such as
`https://example.org/fraud/data/transactions/1`, with no blank nodes.
Sorted N-Triples and sorted-key JSON provide repeatable output in the pinned
runtime. Input filenames, sizes, SHA-256 hashes, selection parameters, counts,
time-key range, and output hash are recorded without absolute input paths.
All four inputs are hashed before and after import to detect changes. This
requires two complete file reads, plus parsing: memory and emitted data are
bounded by the selection, but total input I/O and elapsed time are not.
Use immutable local inputs; a manifest is not proof of publisher provenance.

From the public edition root, with its own Python 3.12 virtual environment:

```powershell
.\.venv\Scripts\python.exe -I -m pip --isolated install --index-url https://pypi.org/simple -r requirements-rdf.txt
.\.venv\Scripts\python.exe -B FastAPI/import_public_data.py --input-dir local-data/kaggle-v1 --limit 1000
```

Place a separately acquired, version-pinned dataset under the ignored input
directory before using that example. The command performs no download. Output
always goes under this edition's ignored `local-data/rdf-first-1000` directory:
`sample.nt` and `manifest.json`. Existing output is never overwritten. Do not
force-add raw data, generated graphs, manifests, or test fixtures to Git.

The exercised local prefix produced 1,000 transactions, 572 users, 702 cards,
658 labeled transactions, zero fraud-positive labels, and 11,624 triples.
One probe over the reloaded graph matched direct calculations on the selected
CSV rows for all 15 features, using a synthetic amount and later cutoff.
This checks transformation consistency only. It is not a training dataset,
fraud demonstration, full-history result, or estimate of model performance.

The public listing names its contributor and declares Apache 2.0. Before
redistributing any subset, verify the acquired files and preserve applicable
license notices and attribution. This project distributes no dataset records.

## Feature rules

- A0 requires exactly one customer/card attribute combination.
- B1 requires a card ID, transaction ID, amount, time key, and a present label.
  Both false and true labels establish population membership. History must be
  strictly earlier than the scoring time.
- B1 counts distinct transaction IDs but averages all matching solution rows.
  Duplicate resources or multivalued properties can bias the average. Ingestion
  must establish canonical identity and single-valued attributes; this feature
  contract does not silently redefine the average.
- C1 requires the same merchant, a present boolean label, and at least 604800
  seconds of lag for the entire eligible population. Card IDs are optional.
- C1 counts distinct transaction/card IDs. A fraud transaction without a card
  contributes to transaction counts only. Zero denominators yield zero rates.
- Empty B1 results normalize to count zero and null average/time before assembly.

These rules describe the reviewed queries. They do not prove real-time label
availability, point-in-time demographics, or full offline/online parity.

## RDFLib implementation notes

1. The tested RDFLib runtime requires `xsd:integer` for integer-valued time
  keys in the B1 filter.
2. C1 uses two filtered aggregate subqueries over the same eligible population
  to avoid engine-dependent error sentinels in conditional distinct counts.
3. pyparsing 3.3.3 emitted upstream deprecation warnings; the tested parser is
  pinned to 3.2.3, and tests pass with warnings treated as errors.

The provider accepts an already-loaded graph and returns feature dictionaries.
It has no network transport or credential handling. Cross-engine equivalence,
persistent-store behavior, and full-data performance have not been established.

## Validation and next gate

Follow the isolated test command in [the report](../FastAPI/SCORE_EVIDENCE_INSPECTION.md).
The data/graph slice has 26 pure-function tests, 16 RDF compatibility cases, and 35 importer
cases in [the ingestion tests](../FastAPI/tests/test_import_public_data.py).
The report also describes the separate model-conversion environment and tests.
Test-generated files stay under ignored `local-data/pytest`, which pytest owns
and clears between runs. Do not store other files there.

Next graph gates are a publisher-verified, version-pinned input acquisition,
representative history checks, and persistent-storage evaluation. Do not load
the full dataset into this small-data harness and call it production-ready.