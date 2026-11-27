---
name: streamlit-app-standards
description: "Verisure standards for Streamlit in Snowflake apps on a compute pool. Use when creating, editing or reviewing a Streamlit app in the verisure-streamlit-cicd repo (apps/<team>/<app>), from a Snowsight Git workspace or from VS Code: scaffolds the app with app.yml, applies the naming, connection, dependency and security rules, and runs the same checklist that blocks the pull request in GitHub Actions. Triggers: new streamlit app, create streamlit app, streamlit standards, streamlit checklist, check my app, app.yml, fix my PR, PR comment FAILED, before I push my streamlit app."
---

# Streamlit app standards (Verisure)

Use this skill to help a developer build a Streamlit app that the CI/CD will accept.
The rules live in `standards.yml` (next to this file). The checklist script
`scripts/check_streamlit_app.py` applies them. **GitHub Actions runs the same script on every
pull request and blocks the merge on any error**, so a PASS here means a PASS in CI.

## Never deploy: the CI/CD does it
Only write and change the files in `apps/<team>/<app_name>/`. **Never create or replace the app in
Snowflake**: no `CREATE STREAMLIT`, `ALTER STREAMLIT`, `snow streamlit deploy`, or any deploy step from
another Streamlit skill. Developer roles don't have that permission; the app reaches
`DB_STREAMLIT.<TEAM>` only through the PR and the CI/CD.
- To try the code, use **Run** in the Snowsight workspace (a private development app that only the
  developer sees) or run it locally; that needs no deploy.
- Don't use the **Deploy** or **Share** buttons in Snowsight: deploys go through the CI/CD, and sharing
  is `viewers` in `app.yml`. Share writes `grants` into `snowflake.yml`, which the checklist rejects.
- When the files are ready and the checklist passes, stop and tell the developer to commit, push and
  open the PR into `dev`.

## Workflow

### 1. Find the context
- Work from the root of the `verisure-streamlit-cicd` repo (it has `config/teams.yml`). The
  developer may be in a Snowsight Git workspace or in VS Code: the files and rules are the same.
- Ask which **team** owns the app and read `config/teams.yml` (team folder, allowed access model
  `allowed_rights`, warehouse) and `config/envs.yml` (database and compute pool per environment).
  If the team is missing, stop: the platform team must add it first.
- Ask for the app name. It must be `snake_case`, 3-40 characters. This becomes the Streamlit
  object name `DB_STREAMLIT.<TEAM>.<APP_NAME>`.
- Test data for the pilot: `DB_STREAMLIT.DEMO_DATA.SALES (COUNTRY, MONTH, AMOUNT)` and
  `DB_STREAMLIT.DEMO_DATA.ORDERS (REGION, CHANNEL, ORDERS, REVENUE)`.

### 2. Access model
The pilot teams only allow **owner's rights** (`rights: owner`): everyone who can open the app
sees the same data, read by the app owner role. Viewers don't need access to the tables.
Connect with `st.connection("snowflake")`.
If a team later allows `caller` (each viewer sees only their own rows), the extra rules in
section 4 apply.

### 3. Scaffold `apps/<team>/<app_name>/` (6 files)
The folder must be a Snowsight Streamlit project, so the workspace shows **Run**.
- `streamlit_app.py`: the entry point.
- `README.md`: what the app does, the data used, and a contact.
- `app.yml` (Verisure rules, read by the CI/CD):
```yaml
name: <app_name>            # same as the folder
title: <Title shown in Snowsight>
description: <one line>
owner_email: <person responsible>
rights: owner               # must be allowed for the team in config/teams.yml
viewers: []                 # roles of any team that can open this app, e.g. AZ-SF-<DOMAIN>-ANALYST
```
- `snowflake.yml` (Snowsight project; one target per environment in `config/envs.yml`, key `dev`).
  Fill the values from `envs.yml` and `teams.yml`; the checklist compares them:
```yaml
definition_version: 2
entities:
  dev:
    type: streamlit
    identifier:
      name: <APP_NAME>              # app name in upper case
      database: DB_STREAMLIT        # envs.yml dev.database
      schema: <TEAM>                # team key in teams.yml
    main_file: streamlit_app.py
    query_warehouse: VWH_STREAMLIT  # team warehouse in teams.yml
    compute_pool: SYSTEM_COMPUTE_POOL_CPU   # envs.yml dev.compute_pool
    runtime_name: SYSTEM$ST_CONTAINER_RUNTIME_PY3_11
    artifacts:
      - streamlit_app.py
      - pyproject.toml
      - .streamlit/config.toml
```
- `pyproject.toml`: **no dependencies**. There is no PyPI access in this environment; the runtime
  already has `streamlit`, `pandas` and `snowflake-snowpark-python`. Use only those. Don't create
  `requirements.txt`.
```toml
[project]
name = "<app-name>"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []
```
- `.streamlit/config.toml`: Streamlit settings; it can stay almost empty:
```toml
[server]
runOnSave = true
```
If Snowsight rewrites `snowflake.yml` (it does when you open Settings: shared values move to a
`streamlit_shared` mixin), that's fine as long as the values still match; run the checklist again.

### 4. Code rules (container runtime on a compute pool)
- Connect with `st.connection(...)`. Never use `get_active_session()` or `_snowflake`: they aren't
  thread-safe on a compute pool.
- No `USE ROLE` and no `USE WAREHOUSE`. The CI/CD sets the owner role and the warehouse.
- No passwords, tokens, keys or account URLs anywhere in the app folder.
- Caller's rights apps only:
  - open `st.connection("snowflake-callers-rights")` at the **top of the script**, not inside a
    function, `if` or page, because the viewer token lasts only 2 minutes;
  - every `@st.cache_data` uses `scope="session"`, so one viewer's rows are never served to another.
- Cache queries with `@st.cache_data(ttl=600)`. Select only the columns you need (`SELECT *` is a
  warning).
- Keep files under 1 MB and read data from Snowflake instead of shipping it in the repo.

### 5. Run the checklist (before every push)
If you can run Python (VS Code, terminal), from the repo root:
```bash
pip install pyyaml==6.0.2   # once
python skills/streamlit-app-standards/scripts/check_streamlit_app.py apps/<team>/<app_name> \
  --head-branch "$(git branch --show-current)" --base-branch dev
```
If the skill was installed from the catalog, the script is in this skill's folder: run it with
`--repo-root <path to the repo>`. If you can't run Python (for example in a Snowsight workspace),
review the files against sections 3 and 4 yourself (in particular `snowflake.yml` and
`pyproject.toml`); the PR runs the same checklist.

- **PASSED** → commit, push the branch and open the PR into `dev`.
- **FAILED** → fix every error using the "How to fix" column, then run it again. Never tell the
  developer to push while there are errors: the PR will be blocked with the same list.
- If a **PR comment reports FAILED**, fix every error listed in "How to fix" and push again to
  the same branch: the same comment is updated.

### 6. Branch flow (explain once)
1. Branch from `dev`: `feature/<team>-<description>` (for example `feature/finance-cost-report`).
2. Push and open a PR into `dev`. The checklist runs and comments on the PR; errors block the merge.
3. On merge, GitHub deploys the app to `DB_STREAMLIT.<TEAM>.<APP_NAME>` (DEV) with no secrets
   (OIDC), on the shared compute pool and the team warehouse, then verifies it.
4. The team engineer role gets access to the app on every deploy.

## Stopping points
- Before scaffolding: confirm the team, app name and access model.
- After the checklist: show the result. Don't continue to a push while there are errors.
