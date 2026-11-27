# Training Evaluation and RDF/SQL Boundary

## Bottom line

The local scoring demo does use an RDF graph: `RdfFeatureProvider` runs
SPARQL queries for A0, B1, and C1, assembles the 15-feature vector, and passes
it to XGBoost through `LocalFraudScoringService`. The tracked graph is a small
synthetic demo fixture.

The exploratory multi-million-row evaluation did **not** use RDF. It read flat
CSV/JSON inputs and constructed same-intent historical features with DuckDB SQL
window functions. No 13-million-row dataset was loaded into an RDF graph. This
run can explore whether adding card/merchant history features helps prediction;
it cannot demonstrate that RDF itself improves model performance or that the
SQL and RDF paths produce identical feature values across the full dataset.

## Dataset provenance gate

As checked on 2026-11-25, Kaggle's public metadata reports dataset version 1,
Apache 2.0, and a total archive size of 1,418,293,535 bytes. The metadata
response does not expose per-file checksums. The four files consumed by the
evaluator total 1,418,288,819 bytes; the remaining 4,716 bytes match the local
`mcc_codes.json`, which the evaluator does not consume. This is a size
consistency check only, not byte-level authentication.

The public listing describes financial transaction data, but does not
independently establish that the local files are exactly that release or
unrelated to any company data. The declared license is useful
metadata, not proof of source identity or clearance of potentially overlapping
records. The local aggregate metrics are included in the private project
candidate at the owner's request, labeled exploratory below and in the README.
Keep raw data out of the repository; do not treat these metrics as public
release clearance until source identity and confidentiality are verified.

## Confidentiality scan

Gitleaks v8.30.1 was downloaded to a temporary directory, its archive SHA-256
was checked against the official GitHub release metadata, and the executable
was removed after use. A redacted filesystem scan found zero findings across
23 selected destination candidate paths: backend source/tests, frontend source
and top-level config/lockfiles, the synthetic graph/model candidates, root
documentation, and requirements. It excluded local datasets/output, virtual
environments, generated dependencies/build output, and Git history. This does
not replace manual review for organization-specific terms or a history scan
before any public push.

## Project and platform scope

This repository is a focused implementation of one fraud-scoring use case, not
a source-by-source copy of the broader application. The wider workflow used
Graph Studio, AI Studio, AI Hub, and Mendix in different portions. Here, the
replacements cover only this scoring slice:

- [Graph Studio](https://www.siemens.com/en-us/products/rapidminer/graph-studio/)'s graph-query role is represented by RDFLib and SPARQL over a
  small in-memory graph. Persistent graph service behavior is not established.
- [AI Studio](https://www.siemens.com/en-us/products/rapidminer/ai-studio/)'s selected model workflow is represented by native XGBoost
  inference and a local evaluation runner. The existing model is an authorized
  conversion; exact AI Studio output parity is not achieved.
- [AI Hub](https://docs.rapidminer.com/latest/hub/)'s selected serving role is represented by a local inference provider
  behind FastAPI. There is no model registry, managed hosting, or operations
  layer here.
- [Mendix](https://www.mendix.com/)'s selected interaction is represented by a React scoring workbench.
  It implements one workflow, not a full low-code application replacement.

The potential value is a testable way to add time-aware card and merchant
history to a local scoring flow. The current evidence does not establish model
uplift, graph-over-SQL advantage, production readiness, or platform parity.
See [the project story](../PROJECT_STORY.md) for the step-by-step rationale.

## Why DuckDB was used

This was an offline analytical job over large flat files: validate/join records,
compute chronological history windows, make a time split, sample training
negatives, and feed numeric matrices to XGBoost. DuckDB offered local SQL joins,
aggregations, and window functions for that workflow, while the JSON label map
was streamed into temporary storage. The evaluator did not need to turn all
source rows into graph triples just to construct and compare the feature stages.

This was an engineering choice, not a measured DuckDB-versus-RDF benchmark. No
claim is made that either storage option is faster or produces better predictions
without identical feature definitions, data, temporal rules, and splits.

The graph value in this solution is architectural rather than proven as an
accuracy gain. RDF represents the transaction, client, card, merchant, and label
relationships directly. SPARQL gives those relationships a reusable vocabulary,
explicit point-in-time filters, and traceable evidence. This can simplify adding
new source systems or relationship-based features, and it keeps the model behind
A0/B1/C1 feature names instead of source-table details. SQL remains appropriate
for a high-throughput offline batch and for controlled feature-stage evaluation.
The five-row RDF/SQL smoke check establishes formula consistency only; it does
not establish full-data parity or graph-attributable model uplift.

## What the two paths do

- **Scoring/demo path:** [`rdf_feature_provider.py`](rdf_feature_provider.py)
  executes queries defined in [`graph_queries.py`](graph_queries.py) against a
  caller-supplied RDFLib graph. [`local_scoring_service.py`](local_scoring_service.py)
  obtains the A0, B1, and C1 state, assembles features, and invokes local
  inference. The tracked graph is invented synthetic fixture data, not a
  representative evaluation dataset.
- **Evaluation path:** [`public_evaluation.py`](public_evaluation.py) parses the
  supplied transaction, user, card, and label files into temporary DuckDB
  tables. SQL computes historical features and produces three new XGBoost
  models under one shared chronological split. It neither reads RDF nor calls
  the scoring/demo graph provider.

The feature definitions have the same intent, but this run did not perform a
full-data row-by-row parity check between SQL-generated and RDF-generated
features. Separate synthetic tests validate portions of the SQL evaluator and
RDF scoring path; they are not an end-to-end RDF training/evaluation run.

### Bounded parity smoke check

The existing RDF sample manifest has the same four local input hashes as the
exploratory SQL run. On that same first-1,000-transaction sample, five
deterministically spaced labeled/modelable rows were compared across all 15
features: all 75 values matched exactly (absolute tolerance `1e-9`). A larger
comparison was too slow with repeated RDFLib SPARQL queries and was stopped.
This is a useful formula smoke check, not full parity evidence: the graph has
partial history, only five rows were checked, and the files remain
publisher-unverified. It does not establish graph-attributable performance
uplift.

## Exploratory input size

The local files resembled version 1 of the public Kaggle transaction-fraud
dataset. Their recorded sizes total 1,418,288,819 bytes (about 1.42 GB):

| Input | Bytes | Purpose |
| --- | ---: | --- |
| `transactions_data.csv` | 1,258,531,040 | Transactions, timestamps, entity IDs, amount |
| `train_fraud_labels.json` | 159,083,088 | Transaction ID to Yes/No label map |
| `cards_data.csv` | 509,860 | Card-to-client relation and credit limit |
| `users_data.csv` | 164,831 | Client age, credit score, and yearly income |

The transaction file had 13,305,915 rows. The label map had 8,914,963 rows:
13,332 fraud and 8,901,631 non-fraud. The evaluator inner-joined on transaction
ID and required valid event time, amount, and matching user/card attributes.
All 8,914,963 supplied labeled rows remained modelable; the other transaction
rows had no supplied label and were not treated as negatives.

Local SHA-256 hashes were recorded, but they were not checked against
publisher-provided checksums. The manifest is marked
`exploratory_provenance_unverified`. Matching file sizes do not authenticate
file contents, so its metrics are not publication evidence.

## Preprocessing and features

The evaluator validates required headers, canonical numeric IDs, unique
transaction/label/user/card IDs, and exact Yes/No labels. It parses timestamps
as `%Y-%m-%d %H:%M:%S`, casts IDs and numeric fields, and removes non-numeric
characters from amount, yearly income, and credit limit before conversion.
Rows with invalid time, missing required base values, or non-finite amount,
income, or limit are excluded. The resulting feature matrices use numeric
`float32`; there is no scaling or one-hot encoding. Empty history and zero
ratio denominators map to zero.

| Stage | Features |
| --- | --- |
| A0 | Amount, yearly income, credit limit, age, credit score |
| A+B (AB) | A0 plus prior card transaction count, prior average amount, amount/prior-average ratio, and hours since previous card transaction |
| A+B+C (ABC) | A+B plus merchant prior transaction count, fraud count/rate, distinct-card count, distinct fraud-card count, and fraud-card ratio |

### C1 feature selection and leakage control

The C1 feature set extends A+B with six merchant-level signals selected to
represent four useful dimensions:

- **Volume:** distinct prior transaction count.
- **Observed fraud:** prior fraud count and fraud rate.
- **Breadth:** distinct prior card count.
- **Concentration:** distinct fraud-card count and fraud-card ratio.

Together, these features test whether a merchant's historical transaction volume,
fraud proportion, and card concentration add information beyond static and card
history. Each rate has an explicit zero denominator: no eligible history yields
zero, rather than an error or unbounded value.

The point-in-time rules are explicit. Card history uses only transaction IDs
strictly earlier than the scoring event, with same-second rows excluded. Merchant
history uses only the same merchant and transactions at least 604,800 seconds
(seven days) earlier than the scoring event. Current, same-time, and future
transactions do not contribute. Both windows are cumulative, so the features
summarize earlier history rather than a rolling seven-day slice.

For training and evaluation, the labeled rows are ordered by event time and
transaction ID before the 80/20 split. Test labels are not used to fit XGBoost,
only to calculate held-out metrics. Negative sampling is restricted to the first
80% training partition; test prevalence remains unchanged. The three feature
stages reuse the same chronological partition and sampled training rows.

This is a strong temporal guard against direct future-row leakage, but it is
not complete label-arrival leakage protection. The source provides a fraud label,
not the date and time that the label became available. The seven-day lag is an
assumption used consistently across features and evaluation. A production
implementation should obtain a label timestamp and model availability explicitly;
otherwise C1 may contain more label information than would be available to an
operating scorer.

Card history uses labeled transactions strictly before the current event (same-
second rows are excluded by the one-second window boundary). Merchant history is
cumulative over labeled merchant events at least 604,800 seconds (seven days)
before the current event, not only events within the preceding seven days. The
current and future events are excluded. Label presence and a seven-day lag do
not establish when the labels would actually have arrived operationally.

## Training and evaluation protocol

Eligible labeled rows are ordered by event time, then transaction ID. The first
80% form training data and the final 20% form the held-out test period. Before
sampling, training contained 7,131,970 rows; test contained 1,782,993 rows,
including 3,117 fraud cases. The test set was not downsampled.

Training retained all 10,215 fraud cases and deterministically selected 20
non-fraud rows per fraud case (204,300 negatives), for 214,515 training rows.
The same selected rows and chronological test set are used for each feature
stage. Each stage is a fresh model; the existing converted C1 model is not used
as though it had been trained under this protocol.

Shared XGBoost settings: `binary:logistic`, `gbtree`, histogram tree method,
maximum depth 6, learning rate 0.1, minimum child weight 1, 150 boosting rounds,
full row/column sampling, L2 regularization 1, L1 regularization 0, one thread,
and seed `949776430`. There was no calibration, hyperparameter search, or
validation-based early stopping.

Predictions are evaluated only on the untouched test set:

- **AUPRC:** step-wise average precision, grouping equal scores at each
  threshold.
- **Review capacity:** rank by predicted fraud probability and inspect the top
  0.1%, 0.5%, and 1.0% of test rows; the reviewed count is rounded up.
- **Queue metrics:** fraud count captured, share of all test fraud captured,
  precision, lift over random selection, and fraud amount captured.
- **Fraud amount:** sum of `max(amount, 0)` for true-fraud rows in the reviewed
  queue. It is an amount in source units, not confirmed USD, recovered money,
  prevented loss, or realized savings.

The README summarizes aggregate metrics newly generated by this repository's
evaluation runner; they were not copied from the earlier project or its
presentation. The full values remain in the ignored
`local-data/public-evaluation-local-exploratory/` output. The full manifest and
models remain ignored. No transaction rows or labels are included in that
output, and no internal presentation figures or C2 results were used. Treat
the displayed values as exploratory because publisher byte identity and the
source currency are unverified.

## What would support the graph claim

A careful current statement is: **the scoring demo uses RDF-derived client,
card, and merchant history features; a separate exploratory SQL evaluation
examined the predictive value of similarly defined history features.** The
current evaluation does not establish a graph-attributable performance uplift.

To make a stronger evidence-based claim, first verify a fresh, version-pinned
dataset and its license. Then generate the training and test features through
the RDF path (or verify SQL/RDF feature parity row by row with temporal-boundary
cases), confirm point-in-time and label-availability assumptions, and evaluate
A0/AB/ABC with the same split and protocol on authenticated data. An A0 versus
AB/ABC comparison would support the value of added historical features; it would
not by itself show that RDF representation is superior to equivalent SQL
features. A separate controlled comparison or benchmark would be needed for
claims about the graph technology itself.

To rerun the exploratory evaluator, place the four inputs in ignored
`local-data/kaggle-v1` and use a new output name:

```powershell
.\.venv\Scripts\python.exe -I -m pip --isolated install --index-url https://pypi.org/simple -r requirements-evaluation.txt
.\.venv\Scripts\python.exe -B FastAPI/public_evaluation.py --input-dir local-data/kaggle-v1 --output-name public-evaluation-v1
```

The runner records local hashes and checks that inputs did not change during
the run. These controls do not establish publisher identity or publication
clearance.
