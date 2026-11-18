# Open-Source Migration Inventory

Status: Steps 1-2 complete; Step 3 local RDF compatibility and bounded ingestion complete.
The graph-to-feature path passes fixture tests and a 1,000-row local-file check.
Publisher-verified inputs, full-history behavior, and persistent storage remain
pending. Step 4 native conversion and same-runtime JSON round-trip checks pass;
vendor-runtime parity, class mapping, and API integration remain open. Converted
artifacts remain quarantined. This is not public-release clearance.

## Scope and boundaries

- The original project is read-only. All migration changes belong here.
- Reuse owned, reviewed code rather than rebuild the application.
- React is the only public application UI. Exclude Mendix entirely.
- The runnable public edition must not require company services or proprietary tools.
- Do not copy existing Git history or initialize/push Git during this step.
- This inventory is not a completed confidentiality audit or legal clearance.
- Ownership of the implementation is user-confirmed; vendor redistribution rights are separate.

## Evidence and working hypothesis

The existing feature assembler defines an explicit ordered 15-feature vector and
does not make network calls. Inference transport is isolated in a separate HTTP
client. Earlier source inspection also identified a separate graph client,
service layer, React scoring/monitoring views, and backend tests.

Working hypothesis: most application and feature logic can be retained, with
localized changes to graph retrieval, inference, configuration, and startup.
This is not yet proof that dependency injection or all imports are portable.

The first executable check passed: 26 feature-assembly and time-key tests run
in a separate destination environment, using independent synthetic fixtures and
no company configuration. Executable AST comparison with the original modules
passed after excluding docstrings and normalizing one local variable rename.
An additional 16 cases test the sanitized queries and local RDF provider,
including graph-to-vector integration. Another 35 cases test bounded CSV/JSON
ingestion, identity, validation, output, and reproducibility. Those 77 tests plus
27 conversion cases pass in the isolated model-conversion environment: 104 total.
A 1,000-row local-file import also matches direct CSV calculations for all 15
features in one probe. This is subset consistency, not model parity. Native model
conversion also preserves probabilities and margins exactly on 72 synthetic
rows in XGBoost 2.1.4. Vendor-runtime parity, full service orchestration, and
persistent-store compatibility remain untested.

## Candidate inventory

Paths below identify original components. Pure modules and selected graph
query/parsing behavior have completed local review and migration. Other
components are not cleared merely because they appear in this table.

| Source component | Treatment | Required review or migration gate |
| --- | --- | --- |
| FastAPI/feature_assembler.py and tests/test_feature_assembler.py | Migrated and tested | Calculation logic retained; documentation sanitized; deployment replay replaced by synthetic cases; feature order, defaults, and numeric behavior tested. |
| FastAPI/time_key.py and tests/test_time_key.py | Migrated and tested | Calculation retained with one local-variable rename; naive timestamps, integer-day anchors, calendar transitions, and microsecond truncation tested. The bounded importer reuses it. |
| FastAPI/feature_service.py and scoring_service.py | Reuse/adapt | Review imports and constructor coupling; substitute providers without changing scoring semantics. |
| FastAPI/main.py and tests/test_api.py | Reuse/adapt | Remove vendor startup requirements and identifying health output; review validation, errors, CORS, and route protection. |
| FastAPI/anzo_mcp_client.py | Selected query behavior migrated | New graph_queries.py and rdf_feature_provider.py pass synthetic RDFLib checks with public namespaces. Casts and conditional aggregates adapted; original transport and diagnostics excluded. Persistent-store parity pending. |
| FastAPI/rapidminer_client.py | Contract inspected; replacement pending | Preserve prediction and both class confidences. The client parses a returned label rather than computing a threshold. Verify native class encoding, threshold/ties, precision, missing values, and error behavior. |
| fraud-ui/fraud-ui/src and frontend configuration | Reuse/adapt | Review sample provenance, text, assets, URLs, and lockfile registry references; retain scoring and monitoring workflow. |
| FastAPI/metrics.py, metrics_store.py, monitoring, load_tests | Reuse/adapt | Remove identifying labels, fixtures, and endpoints; distinguish process-local metrics from aggregate service metrics. |
| FastAPI/auth.py, rbac.py and related tests | Reuse after scoring slice | Review identity-provider assumptions and test credentials; do not migrate local token issuance by default. |
| FastAPI/case_service.py, models.py, database.py, alembic and tests | Defer | Optional investigation scope; retain existing implementation when scheduled, with clean database configuration. |
| Root AI Studio process definitions | Reference selectively | Review XML for credentials, local paths, connections, scripts, and training/evaluation semantics; translate only the selected pipeline if needed. |
| Existing model artifact | Native conversion tested; remains quarantined | XGBoost 2.1.4 loads the legacy payload and saves/reloads JSON with zero probability/margin differences on 72 synthetic probes. Native feature count, objective, booster, and 150 rounds match expectations. Vendor parity, class mapping, final serving runtime, and redistribution review remain open. |
| Existing model/data tables and MLflow databases | Exclude by default | Regenerate public artifacts from documented inputs; local experiment metadata is not publication evidence. |
| Existing project summaries and runbooks | Rewrite public narrative | Reuse verified technical facts, not internal narrative, screenshots, deployment details, or unsupported results. |
| Connections, environment files, certificate/key containers | Exclude | Never copy, print, or stage their contents. Even encrypted credentials and key containers remain excluded. |
| Mendix and other generated application trees | Exclude | No Mendix assets, runtime, binaries, generated source, or deployment output. |
| New_MCP, presentations, saved web pages, office documents, books | Exclude initially | Outside the minimal scoring workflow; reconsider only with an explicit need and rights/content review. |
| Virtual environments, dependencies, caches, logs, builds | Exclude | Reinstall from reviewed manifests; generate only in the destination. |

## Public dataset

Source: https://www.kaggle.com/datasets/computingvictor/transactions-fraud-datasets

Prior web verification found an Apache 2.0 listing, version 1, and credit to
CaixaBank Tech's 2024 AI Hackathon; the Kaggle publisher is ComputingVictor.
Keep required public attribution even though employer deployment information is excluded.
The listing is not independent verification of upstream ownership or synthetic origin.

Use a fresh version-pinned download with checksums and documented preparation.
Do not assume local data exports match the original Kaggle files. Review any
small demo subset, preserve attribution and applicable notices, and identify
modifications when distributing modified data. Full data stays out of Git.
Do not expose unnecessary card/security or identifying fields in demo fixtures.

The bounded importer was exercised against existing local CSV/JSON files after
read-only schema inspection. No fresh download or publisher checksum match was
performed. Ignored output records input SHA-256 hashes and explicitly marks
provenance unverified. The 1,000-row prefix contains 658 labels and zero positive
fraud labels; it is not a representative training/evaluation dataset. Source raw
files were not copied. See [the import guide](graph/README.md#bounded-import).

License reference: https://www.apache.org/licenses/LICENSE-2.0

## Open-source replacement decisions

| Boundary | First candidate | Decision gate |
| --- | --- | --- |
| Graph Studio | RDFLib for local checks; Fuseki remains a persistent-store candidate | Java and Docker unavailable. Fixture and bounded local-file checks pass. No Fuseki validation, full-data import, performance result, or full ontology equivalence is claimed. |
| AI Hub | Native XGBoost inference in the existing API, subject to verification | Legacy-to-JSON conversion and native round-trip checks pass in 2.1.4. Verify vendor class mapping, threshold behavior, original-runtime predictions, and the chosen serving runtime before API integration. Retraining remains a fallback. |
| AI Studio | Existing process as a reproducibility specification | No blanket rewrite. Retrain only when needed, documenting preprocessing, seeds, temporal splits, parameters, threshold, and dependencies. |

An exported model must pass a parity check on reviewed feature vectors, including
probabilities within a declared tolerance and classification decisions. A newly
trained model receives a new version and evaluation; it is not the same model.

Maintain labeled-population membership and strict earlier-time card history, and the existing merchant eligibility
rule: same merchant, present fraud label, and at least seven days of lag for the
eligible population. Preserve distinct-transaction counts and optional-card
semantics. Synthetic tests cover these rules; full-data parity remains pending.
B1 averages solution rows despite counting distinct IDs. The bounded importer
uses one resource per ID, emits single-valued properties, and rejects duplicate
selected transaction IDs and duplicate referenced user/card IDs. These guarantees
do not extend to unselected transactions or arbitrary externally loaded RDF.

## Ordered next steps

1. Complete: establish this inventory and the initial deny-by-default staging policy.
2. Complete: migrate pure feature assembly, time conversion, and adapted tests; establish an independent test environment and pass 26 offline checks.
3. Bounded local check complete: 16 RDF cases and 35 ingestion cases pass alongside the prior 26 tests. A deterministic 1,000-row local prefix was imported and checked. Publisher-verified source acquisition, full-history validation, and persistent storage remain separate gates.
4. Native conversion complete: isolated 2.1.4 legacy loading and JSON round-trip pass on 72 synthetic probes. An ignored CSV contains the exact inputs for offline vendor scoring. Next obtain trusted reference predictions, resolve class/threshold semantics, and validate the selected serving runtime before integration.
5. Migrate the reviewed FastAPI scoring path and React scoring/monitoring UI; verify an end-to-end local demo.
6. Add reproducible data preparation, CI, documentation, licensing, and release review; investigate case management separately if scheduled.

## Current evidence

See [the current migration report](FastAPI/SCORE_EVIDENCE_INSPECTION.md) for
verification details and limitations. A separate ignored .venv
was created here; pytest, RDFLib, and parser dependencies were installed from public PyPI.
The original environment was not reused as the test environment.

Model conversion uses a separate ignored .venv-model-conversion, with pinned
XGBoost, NumPy, and SciPy dependencies. Run the full 104-test gate there. Four
native tests skip when the optional dependencies are absent; such a run is not
the full conversion gate. The test suite trains only a small synthetic booster
and never requires the original model. Generated conversion bundles and probe
results remain ignored under local-data.

Only explicitly reviewed files are allowed by the updated ignore policy.
[The RDF guide](graph/README.md) explains the reconstructed vocabulary and
tested semantics. Dedicated secret scanners are not installed; full release
scanning and actual Git ignore/staging checks remain required.

## What has not happened

No original files modified or original application modules executed. No raw
datasets, original model wrapper, certificates, credentials, vendor adapters,
API entry point, or UI copied. The reviewed native booster was loaded locally;
cleaned JSON and synthetic parity probes were generated only under ignored
local-data, alongside the earlier RDF sample. No company services were called,
Git repository initialized, or publication performed. Vendor model parity,
full-data/persistent-store compatibility, service orchestration, and the
end-to-end application remain unverified. The public application is not runnable yet.