---
name: streamlit-app-standards
description: "Verisure standards for Streamlit in Snowflake apps on a compute pool. Use when creating, editing or reviewing a Streamlit app in the verisure-streamlit-cicd repo (apps/<team>/<app>), from a Snowsight Git workspace or from VS Code: scaffolds the app with app.yml, applies the naming, connection, dependency and security rules, and runs the same checklist that blocks the pull request in GitHub Actions. Triggers: new streamlit app, create streamlit app, streamlit standards, streamlit checklist, check my app, app.yml, fix my PR, PR comment FAILED, before I push my streamlit app."
---

# Streamlit app standards (Verisure)

Use this skill to help a developer build a Streamlit app that the CI/CD will accept.
The rules live in `standards.yml` (next to this file). The checklist script
`scripts/check_streamlit_app.py` applies them. **GitHub Actions runs the same script on every
pull request and blocks the merge on any error**, so a PASS here means a PASS in CI.

## Workflow

### 1. Find the context
- Work from the root of the `verisure-streamlit-cicd` repo (it has `config/teams.yml`). The
  developer may be in a Snowsight Git workspace or in VS Code: the files and rules are the same.
- Ask which **team** owns the app and read `config/teams.yml`: the team folder, the allowed
  access model (`allowed_rights`) and the warehouse. If the team is missing, stop: the platform
  team must add it first.
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

### 3. Scaffold `apps/<team>/<app_name>/`
- `streamlit_app.py`: the entry point.
- `requirements.txt`: **empty**. There is no PyPI access in this environment; the runtime
  already has `streamlit`, `pandas` and `snowflake-snowpark-python`. Use only those.
- `README.md`: what the app does, the data used, and a contact.
- `app.yml`:
```yaml
name: <app_name>            # same as the folder
title: <Title shown in Snowsight>
description: <one line>
owner_email: <person responsible>
rights: owner               # must be allowed for the team in config/teams.yml
viewers: []                 # roles of any team that can open this app, e.g. AZ-SF-<DOMAIN>-ANALYST
```

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
review the files against sections 3 and 4 yourself; the PR runs the same checklist.

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
