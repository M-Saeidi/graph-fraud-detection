# Model Conversion and Native Round-Trip Results

## Outcome

The reviewed legacy XGBoost booster loads successfully in XGBoost 2.1.4 and
converts to native JSON without retraining. Reloading that JSON produces exactly
the same probabilities and raw margins on 72 deterministic synthetic feature
rows. This supports reuse, but is not yet proof of equivalence with the vendor
runtime or clearance to publish the model.

The original model remains unchanged. The converter reads its JSON wrapper,
decodes the booster in memory, and writes only to ignored destination storage.
No company endpoint, original application module, or vendor runtime was executed.

## Implementation

- [convert_model.py](convert_model.py) validates the reviewed wrapper version/type, exact numeric feature order/types, separate label dictionary, objective, iteration count, payload signature, and size before native loading.
- Native checks confirm 15 features, binary:logistic, gbtree, and 150 boosted rounds. Arbitrary booster attributes are removed; public feature names and numeric types are set before saving.
- The converter compares original and reloaded predictions, raw margins, and a diagnostic threshold. It refuses existing output and restricts output to this edition's local-data directory.
- [test_model_conversion.py](tests/test_model_conversion.py) contains 27 cases. Native tests train a small synthetic booster; they do not use or distribute the original model.
- [../requirements-model-conversion.txt](../requirements-model-conversion.txt) pins XGBoost 2.1.4, NumPy 2.2.6, and SciPy 1.15.3, alongside the existing test requirements.

## Verification

| Check | Result |
| --- | --- |
| Full test gate | 104 passed with warnings as errors: 77 existing tests plus 27 conversion cases. |
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

The existing local scoring CSV does not contain all required vendor prediction
columns. No trusted original-runtime baseline for these 72 probes is available
from the inspected inputs, so vendor parity was not run.

Use the generated reference_inputs.csv in a separate offline evaluation process
with the original model and original vendor runtime. Do not edit the original
project or contact company endpoints. Export each input row with prediction(isFraud),
confidence(true), and confidence(false), preserving row correspondence and
recording the exact model identity and runtime version. Keep outputs ignored.

That reference is needed to resolve native probability/class mapping, threshold
and tie behavior, numeric precision, missing values, and iteration selection.
The 72 probes are a starting set, not exhaustive boundary or production testing;
add targeted threshold/missing-value cases for the final parity gate. Declare
probability tolerances before evaluating that comparison and require exact
classification agreement. Merely thresholding native output at 0.5 cannot
substitute for this check.

Only same-version native conversion was tested. The final serving runtime,
API integration, training-data provenance, model redistribution, full dependency
locking/security review, and public release remain separate gates. No training
accuracy or graph-feature uplift is claimed. No Git initialization, commit,
push, or publication occurred.

## Why This Matters

We now have executable evidence that the trained booster can be preserved in an
open native format, avoiding an unnecessary retraining step. The next decision
depends on trusted original-runtime predictions, not more data-to-feature tests.
The API and React migration should not silently assume that unresolved contract.