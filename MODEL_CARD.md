# C1 Fraud Model Card

## Model identification

- Artifact: `models/c1_fraud_model.json`
- Format: native XGBoost JSON
- Role: optional local inference artifact for the C1 scoring demo
- Training status: converted existing artifact; not retrained by this repository
- License: repository Apache License 2.0; model redistribution is owner-authorized
- Integrity: 834,603 bytes; SHA-256 `1e0f9aca631d4d1e80d833234d05ee1296dd684b7d915161223f5bdcc50eacf4`

## Intended use

This artifact demonstrates how a fixed fraud-scoring feature vector can be
assembled from transaction, customer, card, and merchant context and supplied to
local XGBoost inference. It is intended for the synthetic graph and local React
scoring demonstration in this repository.

This artifact does not make decisions about real people or financial accounts.
It should not be used to approve or decline transactions, make customer-facing
risk decisions, or replace a separately reviewed fraud-control process.

## Fixed feature contract

The model declares exactly 15 ordered features:

1. `amount`
2. `yearlyIncome`
3. `creditLimit`
4. `currentAge`
5. `creditScore`
6. `card_prior_txn_count`
7. `card_prior_avg_amount`
8. `amount_vs_card_avg`
9. `time_since_prev_card_txn`
10. `merchant_prior_txn_count`
11. `merchant_prior_fraud_count`
12. `merchant_prior_fraud_rate_pct`
13. `merchant_prior_unique_cards`
14. `merchant_prior_unique_fraud_cards`
15. `merchant_prior_fraud_card_ratio_pct`

A caller must preserve names and order. Values must be numeric and finite. The
feature provider rejects missing values and feature drift through its existing
validation path.

## Input and evidence

A transaction score uses:

- A0: amount and static customer/card attributes.
- B1: strict earlier card history.
- C1: same-merchant labeled history that is at least seven days older than the
  scoring transaction.

The returned evidence contains the historical values supplied to the model, but
those values are not feature-importance explanations. Label-arrival time is not
available in the source data, so the seven-day lag is an explicit approximation
rather than a confirmed label-availability rule.

## Model output

The native provider returns:

- A binary prediction.
- Native fraud and non-fraud probabilities.
- Historical evidence used by the request.
- Per-stage and end-to-end timing values.
- A model-parity status identifying this as a local demonstration artifact.

The UI describes the numeric score as uncalibrated and should not be interpreted
as a calibrated fraud probability or a real-world decision threshold.

## Provenance and limitations

The artifact was converted from an existing owner-authorized XGBoost model and
saved as native JSON. This repository does not retrain it and does not present
it as a newly trained A0, A+B, or A+B+C evaluation model.

The three fresh evaluation models use a separate DuckDB protocol and are not
included with the bundled native model. The synthetic graph is invented fixture
data. Full-data graph/RDF parity, external dataset identity, and persistent graph
behavior have not been established.

## License and redistribution

This model card and repository source are licensed under Apache License 2.0.
Redistribution of the native model is owner-authorized. Third-party dependencies
and external data remain subject to their respective licenses or terms.
