# Security Policy

We take the security of ReviewBench seriously. This document explains how to report vulnerabilities and what is — and isn't — in scope.

## Supported versions

ReviewBench is pre-1.0 and ships from `main`. Security fixes are applied to `main` only; there are no maintained back-branches.

| Version    | Supported          |
| ---------- | ------------------ |
| `main`     | :white_check_mark: |
| < `0.1.0`  | :x:                |

## Reporting a vulnerability

**Please do not open public GitHub issues or pull requests for security problems.** Public reports give attackers a head start before we can ship a fix.

Instead, use **GitHub Private Vulnerability Reporting**:

1. Go to <https://github.com/researchbites/review-bench/security/advisories/new>
2. Fill in the advisory form with:
   - A clear description of the issue and its impact
   - Steps to reproduce (or a proof of concept)
   - The affected commit / version
   - Any suggested mitigations you've identified
3. Submit. The maintainers will be notified privately.

You don't need a CVE in advance — we'll request one if the issue warrants it.

### What to expect

- **Acknowledgement:** within **7 days** of your report.
- **Triage:** we'll confirm whether we can reproduce the issue and classify severity (low / medium / high / critical).
- **Fix timeline:** depends on severity. Critical issues get immediate attention; lower-severity issues are scheduled into the normal release flow.
- **Coordinated disclosure:** we'll work with you on a disclosure timeline. By default we ask for 90 days before public disclosure, but we're flexible.
- **Credit:** if you'd like to be credited, we'll name you in the advisory and release notes. Anonymous reports are also welcome.

## Scope

### In scope

- **Code in this repository** — the CLI, fetchers, parsers, processors, and prompts under `src/` and `cli.py`.
- **Database integrity** — ReviewBench's Cloud SQL Postgres instance is publicly readable by design (see "Data Accessibility" in [`README.md`](README.md)). However, the following **are** in scope and worth reporting:
  - The `user` role having more privileges than read-only (`INSERT`, `CREATEROLE`, `CREATEDB`, etc.)
  - Any path that lets an unauthenticated user mutate `papers`, `comments`, `claims`, `assessments`, or `issues`
  - Privilege-escalation paths from the public `user` account to higher-privileged roles
- **Supply-chain risks** — malicious or compromised dependencies declared in `pyproject.toml`, GitHub Actions used in `.github/workflows/`, or referenced LLM API endpoints.
- **Secrets accidentally committed** to the repo.

### Out of scope

- The fact that the public Cloud SQL credentials are documented in `README.md` — that is **intentional** read-only access for reproducibility, not a misconfiguration. (See above re: privileges that exceed read-only — those *are* in scope.)
- Denial-of-service attacks against the public database. Please don't try to exhaust it.
- Vulnerabilities in third-party services we link to (Google Cloud SQL itself, GitHub, Gemini API, OpenAI API). Report those upstream.
- Social-engineering attacks against maintainers or contributors.
- Issues requiring physical access to a maintainer's machine.

## Safe-harbor

We will not pursue legal action against researchers who:

- Make a good-faith effort to follow this policy
- Report vulnerabilities promptly via the channel above
- Avoid privacy violations, data destruction, and service degradation
- Give us reasonable time to respond and fix the issue before public disclosure

Thank you for helping keep ReviewBench and its users safe.
