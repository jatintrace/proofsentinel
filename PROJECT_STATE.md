# PROJECT_STATE

## Current stage
Stage 5 complete. Next: Stage 6.

## Stage history
- Stage 0 accepted: spec v1.2 frozen and TriageAI tag verified (project commit e925e45)
- Stage 1 accepted: repository, dev tooling, documentation skeleton, MIT license and CI. All four CI jobs were green at commit 9669901
- Stage 2 accepted: testable CLI skeleton at commit 71854d7. All four CI jobs were green on that commit
- Stage 3 accepted: immutable data models at commit 4223dc7. All four CI jobs were green on that commit
- Stage 4 accepted: bounded strict manifest reader and closed-schema validator at commit 1a9b829. All four CI jobs were green on that commit
- Housekeeping after Stage 4: GitHub account renamed, remote and copyright line updated (see Repository)
- Stage 5 accepted: canonical path and link-safety checks at commit b370745. All four CI jobs were green on that commit

## Repository
- https://github.com/jatintrace/proofsentinel (branch main)
- The GitHub account was renamed from Jatin-Gupta-spec to jatintrace. GitHub redirected the old address; origin now points at the new address, and git ls-remote showed the same commit there as locally
- Commits use the GitHub noreply address, which identifies the account by number and is unchanged by the rename
- Open item: confirm the GitHub setting "Block command line pushes that expose my email" is enabled
- Open item: open one recent commit on GitHub and confirm it still shows the profile picture and username
- Open item: the TriageAI and SecureGuard clones may still point at the old username (the redirect works). Updating their remotes is optional and is not part of building ProofSentinel

## Environment (from real command output)
- Python 3.14.6 (only install, py launcher default): %LOCALAPPDATA%\Programs\Python\Python314\python.exe
- Git 2.55.0.windows.2
- VS Code 1.140.0 (x64)
- Windows PowerShell 5.1.26100.9549
- Project root contains a space: D:\cyber projects\ (quote paths in PowerShell)
- Virtual environment: .venv in the repo root. A terminal can activate it with a process-scope policy only (Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned); never use a wider scope. Project commands use the explicit .\.venv\Scripts\python.exe path, so activation is optional
- Dev tools (pytest, Ruff, mypy strict, pip-audit) installed in .venv with pip install -e ".[dev]". Runtime dependencies: none
- This machine cannot create symlinks, but can create Windows junctions without special privileges

## CI
- Workflow: .github/workflows/ci.yml
- Matrix: ubuntu-latest and windows-latest, Python 3.11 and 3.13 (as the spec requires)
- Steps: upgrade pip and setuptools, install ".[dev]", pytest, Ruff, strict mypy, pip-audit
- Permissions: contents: read. Checkout uses persist-credentials: false
- Actions pinned by major version tag: actions/checkout@v6, actions/setup-python@v6
- GitHub sets CI=true. The symlink tests FAIL instead of skipping when CI=true and symlinks cannot be created, so a green CI run means those tests really ran on both operating systems

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
- Module: src/proofsentinel/manifest.py. Tests: tests/test_manifest.py
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
- target.root and target.python are stored exactly as written by the validator. Stage 5's path module resolves and checks them
- validate in the CLI is still not implemented on purpose. Wiring it to the validators alone would report "valid" before the command-plan checks exist, which would be a false pass. It gets wired after the validation pipeline is complete (after Stage 6)
- Test lessons: my first draft had two bad tests (one referenced a removed canary; one put "checks = []" after a [table] header, where TOML scopes it to that table). A scratch run that deliberately broke the validator 21 ways was caught by the tests every time. Exercise: an empty stdout_contains passes on a crash, and a BOM means the reviewed bytes differ from the bytes used

## Path safety (Stage 5)
- Module: src/proofsentinel/paths.py. Tests: tests/test_paths.py. 261 tests in total (93 new)
- Nothing in this module opens, reads, hashes or executes a file, and nothing is created. It is not yet wired into the CLI or the manifest module
- API: resolve_target_root(manifest_path, root), resolve_within_root(root, relative, what, must_exist), resolve_interpreter(root, python), resolve_target(manifest_path, target), preflight_evidence_directory(output, target_root), PathSafetyError, ResolvedInterpreter(entry, final), ResolvedTarget(root, interpreter)
- A relative target.root is relative to the real folder of the manifest file (a symlinked manifest is followed). The root must exist, be a directory and not be a symlink, junction or reparse point. Links further up the path are allowed and resolved to the canonical path
- Relative paths (fixtures, files) use forward slashes and are checked part by part: no empty, "." or ".." parts, no drive letters or leading slash, no characters from < > : " | ? * or backslash, no control or non-printable characters (including the right-to-left override), no trailing space or period, no Windows device names (con, prn, aux, nul, com1-9, lpt1-9, with or without an extension), parts of at most 255 characters and paths of at most 1024
- Any symlink, junction or other reparse point below the target root is rejected, even one that points back inside. A second containment check (resolved path must stay under the root) sits behind it, and a test proves that second layer by switching the first off
- Interpreter: python must be relative to the target root and its entry must be inside it. The final component may be a symlink (the usual Linux venv layout) if the whole chain ends at an existing regular file. The path to EXECUTE is the venv entry, not the resolved system file, because a venv finds its libraries relative to the path it is launched from. A reparse point that is not a symlink is rejected
- Evidence directory preflight: the directory must not exist (a dangling symlink counts as existing), its parent must exist and be a directory, the name must be a safe single name, and it must lie outside the target root. The check is made on the canonical path, so a parent link leading into the target is caught. Creation itself is Stage 9
- UNC and device paths (starting with two slashes or backslashes) and NUL are rejected everywhere
- The reserved-name list exists in both manifest.py and paths.py. A test fails if the two ever differ. They can be merged into one module later
- Tests: 15 symlink tests skip on this machine (reason shown) and fail instead of skipping in CI; 3 Windows-junction tests run on this machine and passed. Local result: 246 passed, 15 skipped
- Test lessons: a scratch run that deliberately broke the path code 28 ways first let 3 survive. The causes were a test fragment loose enough to match a different rule, a fully redundant check (removed), and a missing test for a symlinked manifest. All 28 are now caught
- Exercise: a real junction was created. Windows read through it, ProofSentinel refused it, and the junction was deleted FIRST so the file outside survived (a recursive delete can follow a junction)

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
- 15 ProofSentinel path tests skip on this machine for the same reason. They run, and must pass, in CI.
- Windows PowerShell 5.1 writes UTF-16 with ">" redirection. Write manifests in the VS Code editor as UTF-8, not with ">".
- pip-audit cannot audit proofsentinel itself (not on PyPI). It audits the CI environment after pip and setuptools are upgraded.
- CI runner Python 3.11 ships setuptools 79.0.1, flagged by PYSEC-2026-3447. CI upgrades to setuptools>=83.0.0 before auditing. The finding was fixed, not suppressed.
- Local Python (3.14) is newer than the CI versions (3.11 and 3.13). 3.14 is not in the CI matrix.
- GitHub Actions are pinned by major version tag, not commit ID. Pinning by commit ID is a deferred hardening step. actions/setup-python v7 appears to exist and has not been reviewed.
- Working-tree files use CRLF line endings (VS Code on Windows). Decide a line-ending policy before Stage 13 hashes repository files.
- CheckDefinition has only the fields shared by command and determinism checks. Fields for file, git, release_claim, canary and performance checks are added in the stages that implement them.
- models.py has one suppression: "# noqa: S105" on CheckStatus.PASS. Ruff mistakes the status name for a password. It is a documented false positive, suppressed on that line only.
- The manifest file itself may be a symlink: the operator names it explicitly. The validator and the path module follow it.
- Only the first manifest error is reported. Collecting all errors is a possible later improvement.
- ProofSentinel cannot tell which arguments in a manifest's args are paths. An argument such as ../../secret.json is passed to the target as plain text, and the target reads it with the user's permissions. Declared fixture and file paths must go through resolve_within_root in the stages that add them.
- A path can change between the check and its later use (time-of-check to time-of-use). Later stages verify file identity again before sensitive reads and writes.
- "Target repository" currently means the target root. Stage 13 (Git) may extend this to the Git top-level folder.
- target.python must be relative to the target root. Absolute interpreter paths are not supported in v0.1.
- Relative path backslashes are accepted only where Windows pathlib has already converted them (target.python). Fixture and file paths given as strings must use forward slashes.
- CI runs 261 tests. Green CI shows the CLI contract, the data definitions, the manifest validation and the path checks hold, not that ProofSentinel can run or verify anything yet.

## Decisions
- v0.1 scope is frozen. Any change needs an entry here first.
- License: MIT. The copyright notice uses the GitHub handle jatintrace (renamed from Jatin-Gupta-spec); it can be changed to a real name before wider publication.
- requires-python >= 3.11. Runtime uses the standard library only.
- Time-box / stop rule: not set yet (owner to decide).

## Next
Stage 6: build command plans as immutable Python executable, module and argv structures, and prove hostile shell metacharacters stay inert as plain argument text. Nothing is executed. After Stage 6 the validation pipeline is complete enough to wire the validate command.