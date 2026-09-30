# Branch Protection & CI Gating

This document records the branch protection configuration for the `main` branch.
The settings live in GitHub repository settings (not in this repo), so this file
serves as the source of truth and reproduction reference.

## Goal

No change can be **merged** into `main`, and no **deploy** can run, unless every
CI check defined in [`.github/workflows/tests.yml`](workflows/tests.yml) succeeds.
Merging into `main` does not deploy: production deploys are started manually.

## How merges are gated

The `main` branch has a GitHub branch protection rule that requires the
following status checks to pass before merging:

- `Ruff Lint (Light)`
- `Ruff Lint (Full)`
- `Backend Type Check (mypy)`
- `Dead Code Check (Vulture)`
- `Version Lock Check`
- `Unit Tests (Python 3.14)`
- `Integration Tests (Python 3.14)`
- `Dependency Vulnerability Audit`
- `Frontend Static Checks`
- `Backend Docker Build`
- `Frontend Docker Build`

Additional settings:

| Setting | Value | Effect |
| --- | --- | --- |
| Required status checks | the 11 jobs above | A merge is blocked until all of them are green. |
| `enforce_admins` | `true` | The rule applies to admins too — nobody can bypass failing CI. |
| `strict` (require up to date) | `false` | Branches do not have to be rebased onto the latest `main` before merging. |
| Required pull request reviews | none | Reviews are not enforced by this rule. |

> **Excluded on purpose:** `Deploy (manual)` is a conditional job that never runs
> on pull requests. Marking it as required would block every PR indefinitely, so it
> is not part of the required checks. `Coverage Report (Python 3.14)` is not
> required either, but it runs on every trigger and enforces
> `coverage report --fail-under=70`, so a large coverage regression fails the run.
>
> Unit test shard jobs are also not listed directly. They are gated through
> `Unit Tests (Python 3.14)`, which depends on every shard and fails if any shard
> fails.

## How deploys are gated

The `deploy` job in [`tests.yml`](workflows/tests.yml) declares:

```yaml
needs: [version_lock_check, dependency_audit, lint, lint_full, typecheck_backend, dead_code, unittest, integration_tests, coverage, frontend_checks, docker_backend_build, docker_frontend_build]
if: github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'
```

A push to `main` runs CI but never deploys. To deploy, run the `CI Quality`
workflow manually with `main` selected (Actions tab → **Run workflow**, or
`gh workflow run tests.yml --ref main`). Because of `needs`, the deploy step only
runs after all listed CI jobs succeed in that same run; if any of them fail, the
deploy is skipped automatically. Runs started on other branches skip the deploy.

## Reproducing the configuration

The protection rule was applied via the GitHub REST API:

```bash
cat > branch-protection.json <<'JSON'
{
  "required_status_checks": {
    "strict": false,
    "contexts": [
      "Ruff Lint (Light)",
      "Ruff Lint (Full)",
      "Backend Type Check (mypy)",
      "Dead Code Check (Vulture)",
      "Version Lock Check",
      "Unit Tests (Python 3.14)",
      "Integration Tests (Python 3.14)",
      "Dependency Vulnerability Audit",
      "Frontend Static Checks",
      "Backend Docker Build",
      "Frontend Docker Build"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON

gh api -X PUT repos/<owner>/<repo>/branches/main/protection --input branch-protection.json
```

> **Note:** the status check names must exactly match the `name:` of each job in
> `tests.yml`. If a job is renamed, update both the workflow and this rule.
