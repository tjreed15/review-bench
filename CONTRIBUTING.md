# Contributing to ReviewBench

Thanks for your interest in ReviewBench! This repo accepts contributions **only via fork + pull request**. Direct pushes to `main` are blocked by branch protection — even maintainers go through PRs.

If anything below is unclear, open a draft PR or a discussion and we'll help.

## Ground rules

- Be kind. This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
- Found a security issue? **Do not open a public issue.** See [`SECURITY.md`](SECURITY.md).
- One logical change per PR. Unrelated cleanups belong in their own PR.
- Don't commit secrets, API keys, or `.env` files. Secret-scanning push protection is on; if it blocks you, that's the system working — fix the leak rather than bypassing the check.

## Local setup

```bash
# 1. Fork researchbites/review-bench on GitHub, then clone your fork
git clone git@github.com:<your-username>/review-bench.git
cd review-bench

# 2. (optional) keep your fork in sync with upstream
git remote add upstream git@github.com:researchbites/review-bench.git

# 3. Install in editable mode (Python 3.9+)
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 4. Set up environment variables
cp .env.example .env
# Edit .env — for read-only experimentation you can use the public Cloud SQL
# credentials documented in README.md ("Data Accessibility" section).

# 5. Smoke test
python -m compileall cli.py src/
review-bench --help
```

## Workflow

1. **Branch** from your fork's `main`:
   ```bash
   git checkout -b feat/short-description
   ```
2. **Code** — keep changes focused and follow the existing patterns in `src/`. The pipeline architecture is documented in [`README.md`](README.md#pipeline-architecture); new venues should slot into `src/fetchers/` and `src/parsers/` without modifying downstream stages.
3. **Verify locally** — at minimum:
   ```bash
   python -m compileall cli.py src/
   python -c "import cli; from src.db import queries, schema, client"
   ```
4. **Commit** with a clear message (imperative mood: "Add eLife fetcher", not "Added").
5. **Push** to your fork and **open a PR** against `researchbites/review-bench:main`.
6. **CI** will run automatically on the PR. **First-time contributors:** GitHub will hold the workflow in an "Awaiting approval" state until a maintainer clicks "Approve and run". This is intentional — it prevents fork PRs from running arbitrary code in our CI without review. Don't worry, it's a one-click approval and not a reflection on your PR.
7. **Review** — a maintainer from `@researchbites/maintainers` will review. The PR template's checklist is your friend.
8. **Merge** — once approved, with passing checks, conversations resolved, and an up-to-date branch, your PR will be squash-merged.

## What gets reviewed

Reviewers focus on:

- **Correctness** — does the code do what the PR description says?
- **Scope** — is the diff focused, or has it grown into an unrelated refactor?
- **Schema alignment** — new venues must produce data that conforms to the canonical `papers` / `comments` / `claims` / `assessments` tables described in [`README.md`](README.md). Fetchers and parsers should be the only venue-specific code.
- **Tests** — new behavior should have tests where practical.
- **Secrets hygiene** — no credentials, no `.env` files, no hard-coded API keys.
- **Docs** — if you changed CLI behavior or pipeline shape, update `README.md`.

## Security

Security issues go through GitHub Private Vulnerability Reporting. See [`SECURITY.md`](SECURITY.md) for the full process. **Never** report a vulnerability in a public PR or issue.

## Code of Conduct

This project adheres to the [Contributor Covenant v2.1](CODE_OF_CONDUCT.md). By participating, you agree to abide by its terms.

## Maintainers

PRs are auto-routed to `@researchbites/maintainers` via [`CODEOWNERS`](.github/CODEOWNERS). Mention the team in a PR comment if you need attention.
