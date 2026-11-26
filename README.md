# verisure-streamlit-cicd

Streamlit (container runtime, compute pool) and CoCo skill CI/CD for the Verisure pilot.
Snowflake account: Verisure DEV (GitHub repo variable `SNOWFLAKE_ACCOUNT`), database `DB_STREAMLIT`.

## How it works
1. A developer builds an app in `apps/<team>/<app_name>/` with CoCo and the skill
   `/streamlit-app-standards` (4 files: `streamlit_app.py`, `app.yml`, `requirements.txt`, `README.md`).
2. Pull request into `dev`: GitHub runs the standards checklist, posts a comment with what failed and
   how to fix it, and **blocks the merge** on errors (`app-checks`, `skill-checks`).
3. Merge into `dev`: GitHub logs in to Snowflake with OIDC (no secrets) and deploys only the changed apps
   to `DB_STREAMLIT.<TEAM>.<APP>`, then verifies owner, compute pool, warehouse, runtime and commit.

## Pilot setup
| | Value |
| --- | --- |
| Pipeline role (creates and owns the apps) | `STREAMLIT_CICD_DEV` |
| Service user (OIDC, GitHub environment `dev`) | `SVC_STREAMLIT_CICD_DEV` |
| Compute pool (shared by all apps) | `SYSTEM_COMPUTE_POOL_CPU` |
| Warehouse | `VWH_STREAMLIT` (per team in `config/teams.yml`) |
| PyPI access | none: `requirements.txt` must be empty |
| Access model | owner's rights |

## Layout
| Path | What |
| --- | --- |
| `apps/<team>/<app>/` | the apps (developers) |
| `skills/streamlit-app-standards/` | the skill: `SKILL.md`, `standards.yml` (rules), checklist script |
| `config/teams.yml`, `config/envs.yml` | teams and environments |
| `ci/` | deploy script, skill validation, unit tests |
| `.github/workflows/` | `pr-checks`, `deploy-apps`, `demo-data` (manual), `connection-test` (manual) |
| `snowflake/00_admin_setup.sql` | one-time admin setup (already run) |
| `snowflake/90_demo_data.sql` | test data for the sample apps |
| `demo/DEMO.md`, `demo/reference/` | demo script (Snowsight + VS Code) and reference code; never deployed |
| `requirements-dev.txt`, `.vscode/` | local checklist and tests in VS Code |
