# PROJECT_STATE

## Current stage
Stage 4 complete. Next: Stage 5.

## Stage history
- Stage 0 accepted: spec v1.2 frozen and TriageAI tag verified (project commit e925e45)
- Stage 1 accepted: repository, dev tooling, documentation skeleton, MIT license and CI. All four CI jobs were green at commit 9669901
- Stage 2 accepted: testable CLI skeleton at commit 71854d7. All four CI jobs were green on that commit
- Stage 3 accepted: immutable data models at commit 4223dc7. All four CI jobs were green on that commit
- Stage 4 accepted: bounded strict manifest reader and closed-schema validator at commit 1a9b829. All four CI jobs were green on that commit

## Repository
- https://github.com/Jatin-Gupta-spec/proofsentinel (branch main)
- Commits use the GitHub noreply address
- Open item: confirm the GitHub setting "Block command line pushes that expose my email" is enabled

## Environment (from real command output)
- Python 3.14.6 (only install, py launcher default): %LOCALAPPDATA%\Programs\Python\Python314\python.exe
- Git 2.55.0.windows.2
- VS Code 1.140.0 (x64)
- Windows PowerShell 5.1.26100.9549
- Project root contains a space: D:\cyber projects\ (quote paths in PowerShell)
- Virtual environment: .venv in the repo root. A terminal can activate it with a process-scope policy only (Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned); never use a wider scope. Project commands use the explicit .\.venv\Scripts\python.exe path, so activation is optional
- Dev tools (pytest, Ruff, mypy strict, pip-audit) installed in .venv with pip install -e ".[dev]". Runtime dependencies: none

## CI
- Workflow: .github/workflows/ci.yml
- Matrix: ubuntu-latest and windows-latest, Python 3.11 and 3.13 (as the spec requires)
- Steps: upgrade pip and setuptools, install ".[dev]", pytest, Ruff, strict mypy, pip-audit
- Permissions: contents: read. Checkout uses persist-credentials: false
- Actions pinned by major version tag: actions/checkout@v6, actions/setup-python@v6

## CLI (Stage 2)
- Entry points: python -m proofsentinel (src/proofsentinel/__main__.py) and cli.main(argv) -> int in src/proofsentinel/cli.py
- Commands that parse: validate <manifest>, run <manifest> --output <dir>, verify-evidence <dir>. Parsing opens no files
- All three commands are not implemented yet and return exit code 2 (fail closed), never 0
- Exit codes are in the ExitCode IntEnum: OK 0, CHECKS_FAILED 1, ERROR 2, USAGE 3. Usage errors return 3 with no traceback (argparse's default of 2 is overridden). --help returns 0
- Text echoed back from the command line has non-printable characters (escape characters, newlines) shown as visible escapes
- Tests set NO_COLOR and PYTHON_COLORS=0 so argparse output stays plain on newer Pythons
- Test lesson: changing the unimplemented-command return code to 0 passed Ruff and mypy but failed 3 behavior tests

## Data models (Stage 3)
- Module: src/proofsentinel/models.py. Tests: tests/test_models.py
- 14 dataclasses (Limits, TargetDescriptor, CanaryRegistration, Assertion, CheckDefinition, Manifest, InvocationResult, AssertionResult, CheckResult, Totals, CanonicalResults, RunMetadata, EvidenceIndexEntry, EvidenceIndex), all frozen, slotted and keyword-only. A generic test enforces this for every model class
- StrEnums: CheckType (the 7 v0.1 check types), CheckStatus (PASS, FAIL, ERROR only; no SKIP), AssertionKind, GitObjectFormat, CompletionState
- Hard ceilings from the contract are constants (200 checks, 100 invocations, 600 s per command, 1800 s overall, 1 MiB streams, argv limits, 100 MiB file hashing)
- Defaults fail closed: expected_exit 0, require_clean_git True
- CanaryRegistration.value is hidden from repr(), but dataclasses.asdict() still exposes it (shown in the Stage 3 exercise). Rule for Stage 9: the evidence writer must never receive a Manifest or CanaryRegistration. It accepts only result models and converts them with explicit, hand-written field lists, never asdict() or vars(). The whole-bundle canary scan (Stage 12) is a second layer, not the only one
- Models validate nothing. The manifest validator is the only door manifest data may pass through
- Test lesson: a first draft of the keyword-only test still passed with the protection removed. Breaking the code on purpose exposed it, and the test was rewritten

## Manifest validator (Stage 4)
- Module: src/proofsentinel/manifest.py. Tests: tests/test_manifest.py. 168 tests pass in total
- API: read_manifest_bytes(path) -> bytes, parse_manifest(bytes) -> Manifest, ManifestError. There is deliberately no all-in-one load function: read the file once, hash those exact bytes for the evidence, and parse the same bytes
- Reading: stat before open (refuses pipes and non-regular files without blocking), fstat on the opened file, read of at most 1 MiB + 1 byte, then an explicit too-large check
- Decoding: strict UTF-8; UTF-8, UTF-16 and UTF-32 byte order marks are rejected; tomllib rejects duplicate keys; over-deep nesting is rejected without crashing
- Closed schema: unknown keys are errors at every level. Top-level keys: schema_version, target, modules, limits (optional), canaries (optional), checks. schema_version must be exactly 1
- Types are strict: true is not accepted as an integer, and strings are not converted to numbers. Every identifier pattern uses fullmatch, so a trailing newline is rejected
- Supported check types: command and determinism only. The other five known types (file, git, release_claim, canary, performance) are rejected with "not supported yet" until their stages
- Rejected on purpose: zero checks, empty stdout_contains or stderr_contains strings, duplicate check ids, Windows reserved device names as check ids, a determinism check with fewer than 2 repetitions, a command check with repetitions, modules outside modules.allow, expected_exit outside 0 to 255
- Limits enforced: 200 checks, 100 total invocations after expanding repetitions, 128 args, 4096 bytes per arg, 16 KiB args in total, 600 s per command, 1800 s overall, 1 MiB per stream
- Canaries: values must match PS_TEST_[A-Z0-9_]{8,120} and be unique. A canary value in an argument is rejected. No error message ever contains a canary value. Untrusted text in errors is shown with repr(), so control characters appear as escapes
- Only the first error is reported (deterministic). Errors name the field, for example checks[0].stdout_contains[0]
- target.root and target.python are stored exactly as written. They are not resolved or checked. That is Stage 5
- validate in the CLI is still not implemented on purpose. Wiring it to this validator alone would report "valid" before path and command-plan checks exist, which would be a false pass. It gets wired after the validation pipeline is complete
- Test lessons: my first draft had two bad tests (one referenced a removed canary; one put "checks = []" after a [table] header, where TOML scopes it to that table). A scratch run that deliberately broke the validator 21 ways was caught by the tests every time. Exercise: an empty stdout_contains passes on a crash, and a BOM means the reviewed bytes differ from the bytes used

## Frozen inputs
- Spec: spec\ProofSentinel_Final_Project_Specification_Audited_v1.2.md
- Spec size: 41283 bytes
- Spec SHA-256: D7EEF7067C2B89ADE460AEA3CB5592A03C0DE063F9CEE485BF95D643DE3F7CF3
- TriageAI tag: v0.1.0 (annotated)
- TriageAI commit: 7c1aa86e6253dda3ff23c510bce0cf74da01c036
- TriageAI working tree clean when checked
- TriageAI tests at that commit: 424 passed, 7 skipped

## Known limitations (recorded, not hidden)
- 7 TriageAI tests skipped: tests\test_input_links.py:31, "cannot create symlinks in this environment". Symlink handling is not exercised on this machine.
- The same limitation will affect ProofSentinel's link and reparse tests (Stage 5). Decide how to handle it then.
- Windows PowerShell 5.1 writes UTF-16 with ">" redirection. Write manifests in the VS Code editor as UTF-8, not with ">".
- pip-audit cannot audit proofsentinel itself (not on PyPI). It audits the CI environment after pip and setuptools are upgraded.
- CI runner Python 3.11 ships setuptools 79.0.1, flagged by PYSEC-2026-3447. CI upgrades to setuptools>=83.0.0 before auditing. The finding was fixed, not suppressed.
- Local Python (3.14) is newer than the CI versions (3.11 and 3.13). 3.14 is not in the CI matrix.
- GitHub Actions are pinned by major version tag, not commit ID. Pinning by commit ID is a deferred hardening step. actions/setup-python v7 appears to exist and has not been reviewed.
- Working-tree files use CRLF line endings (VS Code on Windows). Decide a line-ending policy before Stage 13 hashes repository files.
- CheckDefinition has only the fields shared by command and determinism checks. Fields for file, git, release_claim, canary and performance checks are added in the stages that implement them.
- models.py has one suppression: "# noqa: S105" on CheckStatus.PASS. Ruff mistakes the status name for a password. It is a documented false positive, suppressed on that line only.
- The manifest file itself may be a symlink: the operator names it explicitly and the spec only restricts links for target roots and evidence paths. The validator follows it.
- Only the first manifest error is reported. Collecting all errors is a possible later improvement.
- CI runs 168 tests. Green CI shows the CLI contract, the data definitions and the manifest validation hold, not that ProofSentinel can run or verify anything yet.

## Decisions
- v0.1 scope is frozen. Any change needs an entry here first.
- License: MIT. The copyright notice uses the GitHub handle Jatin-Gupta-spec (can be changed before wider publication).
- requires-python >= 3.11. Runtime uses the standard library only.
- Time-box / stop rule: not set yet (owner to decide).

## Next
Stage 5: canonical target, Python, fixture and evidence paths with traversal and link tests. Paths are resolved and checked against the target root; nothing is executed. Symlink tests will skip on this machine, so CI must show them running.