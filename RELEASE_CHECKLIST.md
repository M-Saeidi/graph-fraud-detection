# Public Release Readiness

Use this checklist before sharing a release. Passing it is a review step, not a
guarantee that the project is risk-free.

## For each project change

- [ ] Confirm the change supports the focused, open-source scoring use case.
- [ ] Review the complete source and fixtures locally; report locations/categories, not secrets.
- [ ] Remove corporate hosts, accounts, tenant/project identifiers, private paths, and internal narrative.
- [ ] Review comments, examples, assets, metadata, lockfiles, URLs, and error/health output.
- [ ] Establish provenance and redistribution rights for any data, model, or third-party asset.
- [ ] Include only cleared files and document important design decisions.
- [ ] Extend the .gitignore allowlist narrowly; never allow entire unreviewed trees.
- [ ] Run focused checks in the destination without reading the original environment configuration.
- [ ] Preserve feature contracts or explicitly version and evaluate intentional changes.

## Before initializing or staging Git

- [ ] Confirm no original Git history, connection exports, certificates, keys, environments, logs, database dumps, or unreviewed binary artifacts are present.
- [ ] Run a local secret scanner with redacted output and manually review corporate identifiers.
- [ ] Keep scanner reports and private search terms outside public tracked files.
- [ ] Check the exact proposed tracked file list. Ignore rules can be overridden and do not sanitize files.

## Before a public push or release

- [ ] Review staged content and all new Git history, not just the latest working tree.
- [ ] Repeat local secret scanning on the release content and history; resolve findings.
- [ ] Inspect screenshots, downloadable artifacts, notebooks, and other non-text content separately.
- [ ] Preserve required licenses and notices; do not claim vendor endorsement.
- [ ] Verify a clean checkout can reproduce the documented local scoring workflow without proprietary services.
- [ ] Run backend tests, frontend checks, and a browser end-to-end scoring test in CI.
- [ ] Publish only reproducible evaluation results and clearly label fixtures and limitations.
- [ ] Before public hosting, protect costly endpoints, restrict CORS, disable demo token issuance, and redact logs.
- [ ] Get an explicit publication decision before a public push.

Secret scanning reduces risk but does not prove absence of confidential material.
If a credential is discovered in a public artifact, revoke/rotate it through the
owner before treating history removal as remediation.