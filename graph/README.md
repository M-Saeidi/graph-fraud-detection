# RDF Compatibility Layer

This layer runs reviewed A0/B1/C1 feature queries against RDFLib's in-memory
graph. It is a small-data compatibility harness, not a deployed replacement for
a persistent RDF server. Java and Docker were unavailable locally; Apache Jena
Fuseki has not been installed or tested.

## Vocabulary versus data

[schema.ttl](schema.ttl) is a minimal RDFS description reconstructed from the
predicates used by the reviewed queries, not an export of the full original
ontology. Private namespace IRIs were replaced with reserved example namespaces;
predicate local names were retained to make migration comparisons straightforward.

The vocabulary describes customer, card, and transaction resources. Card and
merchant references remain numeric ID literals, matching the existing queries.
No new ownership edges or inference rules were invented. A0 uses independent
customer/card lookups and does not verify ownership.

| Logical field | Predicate | Mapping contract |
| --- | --- | --- |
| Customer ID | usr:UsersData.id | Canonical integer |
| Age / credit score | usr:UsersData.currentAge / usr:UsersData.creditScore | Integer attributes |
| Yearly income | usr:UsersData.yearlyIncome | Money lexical value normalized by the provider |
| Card ID / limit | card:CardsData.id / card:CardsData.creditLimit | Integer / money lexical value |
| Transaction ID | tx:TransactionsData.id | Canonical integer |
| Card / merchant reference | tx:TransactionsData.cardId / tx:TransactionsData.merchantId | Integer IDs; missing cards are not fabricated |
| Amount | tx:TransactionsData.amount | Money lexical value normalized in SPARQL |
| Time key | feat:transactionTimeKey | Migrated integer-day scale in seconds, not Unix time |
| Fraud label | feat:isFraud | RDF boolean only when a label is present; absence is not false |

Prefix IRIs are declared in the schema. They are identifiers, not services to
call. RDFS domain/range declarations describe meaning; they do not enforce
constraints. The importer validates selected identities, required references,
and value encodings. SHACL validation and complete ontology comparison remain
future work. No reasoning is required here.

The intended public source is the attributed Kaggle dataset in the
[inventory](../MIGRATION_INVENTORY.md). A local-file prefix has been imported;
its original download identity is unverified. No raw files are distributed.
Hand-authored Turtle fixtures in
[the query tests](../FastAPI/tests/test_graph_queries.py) test known expected
results, not real-world accuracy or source-data provenance.

## Bounded import

[The importer](../FastAPI/import_public_data.py) selects the first N data rows in
CSV order, with an explicit limit from 1 to 10,000. It does not shuffle, sort,
balance classes, or reconstruct complete history. It loads only users/cards
referenced by that prefix and streams the entire fraud-label mapping while
retaining only selected labels. Unselected transactions are not validated.

Verified local headers and sample formats map as follows. The Kaggle page
confirms the file set and version, not the byte identity of these local files.

| Input | Selected columns | RDF mapping |
| --- | --- | --- |
| transactions_data.csv | id, card_id, merchant_id, amount | Corresponding TransactionsData predicates above; integers and xsd:decimal money |
| transactions_data.csv | date | Exact naive YYYY-MM-DD HH:MM:SS, converted with the existing time-key function |
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

Public attribution remains ComputingVictor's Kaggle listing, which credits
CaixaBank Tech's 2024 AI Hackathon and lists Apache 2.0. Before redistributing
any subset, verify acquisition provenance, preserve applicable license/notices,
and identify modifications. This implementation distributes no dataset records.

## Retained feature rules

- A0 requires exactly one customer/card attribute combination.
- B1 requires a card ID, transaction ID, amount, time key, and a present label.
  Both false and true labels establish population membership. History must be
  strictly earlier than the scoring time.
- B1 counts distinct transaction IDs but averages all matching solution rows.
  Duplicate resources or multivalued properties can bias the average. Ingestion
  must establish canonical identity and single-valued attributes; the migration
  does not silently redefine this average.
- C1 requires the same merchant, a present boolean label, and at least 604800
  seconds of lag for the entire eligible population. Card IDs are optional.
- C1 counts distinct transaction/card IDs. A fraud transaction without a card
  contributes to transaction counts only. Zero denominators yield zero rates.
- Empty B1 results normalize to count zero and null average/time before assembly.

These rules describe the reviewed queries. They do not prove real-time label
availability, point-in-time demographics, or full offline/online parity.

## Observed portability changes

1. RDFLib 7.1.4 did not evaluate the original xsd:long SPARQL constructor. B1
   uses xsd:integer for valid integer-valued time keys. Validate that domain on import.
2. Error-valued conditional distinct counts inflated C1 fraud counts in this
   engine. Two filtered aggregate subqueries now compute total and fraudulent
   counts over the same eligible population without error sentinels.
3. pyparsing 3.3.3 emitted upstream deprecation warnings. The tested parser is
   pinned to 3.2.3; all tests pass with warnings treated as errors.

No corporate transport, credentials, response dumps, or endpoints were migrated.
The provider accepts an already-loaded Graph and returns existing dictionaries.
Cross-engine equivalence and full-data performance have not been established.

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