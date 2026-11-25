# Model Conversion, Native Round-Trip, and Local Inference

## Local inference milestone

A new vendor-independent `XGBoostInferenceProvider` now loads a native JSON model,
validates the exact 15-feature contract, and returns the existing prediction,
fraud-confidence, and non-fraud-confidence fields. It requires an explicit
`native_probability_is_fraud` setting and configurable threshold; it does not
assume native probability semantics from the model metadata.

The provider was verified by 15 focused tests, and the combined suite passed
120 tests with warnings as errors. Provider tests cover exact feature names,
numeric/finite values, missing/extra features, threshold and mapping flags,
missing models, feature drift, and stable prediction output.

`LocalFraudScoringService` now composes RDF A0/B1/C1 retrieval, the existing
15-feature assembler, and local XGBoost inference. One integration test verifies
the full graph-to-model path and response/evidence/timing shape using a synthetic
graph and synthetic test model. The response explicitly identifies its
`not_exactly_equivalent_to_ai_studio` demo status.

Portfolio-demo decision: proceed with this native model to demonstrate the
project pipeline, provided the observed RapidMiner mismatch is disclosed and no
accuracy/parity claim is made. Confidence differs on 30/72 probes and the 0.5
decisions differ on two. This is not production scoring or proof of exact vendor
reproduction. The local service is not yet connected to HTTP/React.

---

# Model Conversion and Native Round-Trip Results

## Outcome

The reviewed legacy XGBoost booster loads successfully in XGBoost 2.1.4 and
converts to native JSON without retraining. Reloading that JSON produces exactly
the same probabilities and raw margins on 72 deterministic synthetic feature
rows. This supports reuse, but is not yet proof of equivalence with the vendor
runtime. The project owner confirms the model may be used in the GitHub project;
that permission does not resolve the remaining prediction-parity issue.

The original model remains unchanged. The converter reads its JSON wrapper,
decodes the booster in memory, and writes only to ignored destination storage.
No company endpoint, original application module, or vendor runtime was executed.

## Implementation

- [convert_model.py](convert_model.py) validates the reviewed wrapper version/type, exact numeric feature order/types, separate label dictionary, objective, iteration count, payload signature, and size before native loading.
- Native checks confirm 15 features, binary:logistic, gbtree, and 150 boosted rounds. Arbitrary booster attributes are removed; public feature names and numeric types are set before saving.
- The converter compares original and reloaded predictions, raw margins, and a diagnostic threshold. It refuses existing output and restricts output to this edition's local-data directory.
- [test_model_conversion.py](tests/test_model_conversion.py) contains 27 cases. Native tests train a small synthetic booster; they do not use or distribute the original model.
- [local_scoring_service.py](local_scoring_service.py) composes the injected RDF feature provider and XGBoost inference provider without HTTP or vendor dependencies.
- [test_local_scoring_service.py](tests/test_local_scoring_service.py) verifies the complete synthetic graph-to-model demo path.
- [../requirements-model-conversion.txt](../requirements-model-conversion.txt) pins XGBoost 2.1.4, NumPy 2.2.6, and SciPy 1.15.3, alongside the existing test requirements.

## Verification

| Check | Result |
| --- | --- |
| Full test gate | 120 passed with warnings as errors: calculation, RDF, import, conversion, local inference, and local scoring-service tests. |
| Environment | Independent Python 3.12.1 environment; XGBoost 2.1.4, NumPy 2.2.6, SciPy 1.15.3. The earlier environment was not changed. |
| Real artifact loading | Successful; no native load warnings. |
| Probe population | 72 rows spanning three demographic profiles, eight amounts including negative/zero values, and empty/ordinary/high-fraud historical states. No source transaction records used. |
| Probability difference | Maximum absolute difference 0.0; declared tolerance 1e-7 absolute, 0 relative. |
| Raw-margin difference | Maximum absolute difference 0.0 under the same tolerance. |
| Diagnostic >= 0.5 decisions | Zero changes; 29 probes below and 43 at/above the threshold. This is not a verified vendor threshold or fraud-class mapping. |
| Integrity | Original source hash unchanged; generated model and probe hashes checked. Converted user attributes empty and feature names match the contract. |
| Reference CSV | Exact same 72 synthetic input rows and 15 columns exported; equivalence and file hash covered by tests. |

The final bundle is under ignored local-data/model-parity-preparation:

- model.json: native model, with user attributes cleared.
- probes.json: synthetic inputs and native probabilities/margins, explicitly not labeled as fraud confidences.
- reference_inputs.csv: those same inputs for offline original-runtime scoring.
- manifest.json: source/payload/output hashes, versions, contract, tolerances, results, and an explicit no-release-clearance status.

The earlier exploratory bundle under local-data/model-conversion was preserved,
not overwritten. Neither bundle nor the conversion environment is allowlisted.

## Reproduce

From the public edition root, create the conversion environment only if absent:

```powershell
py -3.12 -m venv .venv-model-conversion
.\.venv-model-conversion\Scripts\python.exe -I -m pip --isolated install --index-url https://pypi.org/simple -r requirements-model-conversion.txt
$previousAutoload = $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
try {
	.\.venv-model-conversion\Scripts\python.exe -I -B -m pytest -q -W error -c pytest.ini
} finally {
	$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = $previousAutoload
}
```

Four native tests skip if optional conversion dependencies are absent. A skipped
run is not the full conversion gate. Tests need no external services; installing
dependencies contacts public PyPI. The original model is not required by tests.

For conversion, set $reviewedModel to the path of the existing reviewed artifact;
no source copy is needed. Choose an unused output name:

```powershell
.\.venv-model-conversion\Scripts\python.exe -B -W error FastAPI/convert_model.py --source-model $reviewedModel --acknowledge-local-model-review --output-name model-parity-next
```

Use only reviewed, trusted local artifacts. A virtual environment separates
dependencies; it is not an operating-system security sandbox. Header checks do
not make a native model parser safe for arbitrary untrusted input. The converter
is a local migration tool, not a public model-upload endpoint. Unexpected native
warnings fail conversion; a specifically recognized legacy-compatibility warning
is recorded if encountered. No warnings were encountered for this artifact.

## Remaining Parity Gate

An offline AI Studio run produced a 72-row, 18-column reference CSV using the
repository entry `//KG+AIML/C1_Fraud_Model`. The local repository index resolves
that filesystem repository to the original project directory, and the model
file's SHA-256 matches the conversion manifest's source hash. Its 15 input
columns also match all 72 synthetic probe rows exactly. Wrong model bytes and
input parsing/order/value differences are therefore ruled out. The export contains the expected
`prediction(isFraud)`, `confidence(true)`, and `confidence(false)` columns.

| Comparison | Result |
| --- | --- |
| Vendor confidence consistency | `confidence(true)` and `confidence(false)` sum to 1 on every row. Vendor labels match `confidence(true) >= 0.5` on all 72 rows; none of the observed rows distinguish `>` from `>=`. |
| Class orientation | `confidence(true)` is closer to native XGBoost probability than its complement. This is evidence for orientation, not confidence parity. |
| Confidence parity | Native probability vs vendor `confidence(true)`: maximum absolute difference 0.4360636; mean absolute difference 0.0676034. Thirty rows differ by more than 0.01. Vendor `confidence(false)` has the corresponding complement difference. |
| Decision parity at 0.5 | Native probability thresholded at 0.5 agrees with vendor `prediction(isFraud)` on 70 of 72 rows; two decisions differ. |

**Parity is not achieved. Do not configure production local scoring from this
comparison.** The inputs and vendor label/confidence relationship are now
verified, but the native model does not reproduce the vendor confidence values
or every decision. The exact model bytes loaded from the AI Studio repository
have now been hash-matched to the inspected `.rmtabmod` source. The remaining
difference is in evaluation/runtime behavior rather than model identity or
input data. The installed extension JAR contains XGBoost4J 1.4.1 metadata.
Direct legacy-model inference in Python XGBoost 1.4.1, 1.4.2, 1.7.6, 2.0.3,
and 2.1.4 produced byte-identical probability and margin vectors on these rows;
all four runtimes retain the same 30 confidence differences and two decision
mismatches. This rules out a simple Python XGBoost version difference, but does
not prove Java/Python wrapper equivalence or identify the exact discrepancy.

Next, inspect the AI Studio XGBoost4J wrapper's feature-matrix construction,
output transformation, and prediction options against the Python inference path.
Do not install more Python versions or tune a threshold to hide confidence
mismatches. Keep the vendor export ignored; it contains only synthetic inputs
with local model outputs, not the original transaction data.

The 72 probes remain a focused starting set, not exhaustive threshold,
missing-value, or production testing. Only same-runtime native JSON round-trip
equality is established; vendor equivalence, API integration, training-data
provenance, dependency/security review, and public release remain separate gates.
The converted model is already present under ignored
`local-data/model-parity-preparation/model.json`; it has not been added to Git.

Only same-version native conversion was tested; the first vendor comparison
found confidence and decision mismatches. The final serving runtime, API
integration, training-data provenance, full dependency
locking/security review, and public release remain separate gates. No training
accuracy or graph-feature uplift is claimed. No Git initialization, commit,
push, or publication occurred.

## Why This Matters

We have executable evidence that the trained booster can be preserved in an open
native format and used for a disclosed portfolio demo without retraining. Exact
RapidMiner confidence/decision parity is not achieved; HTTP and React integration
must clearly disclose that limitation rather than present the native scores as
identical to the original runtime.