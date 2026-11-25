---
name: streamlit-app-standards
description: "Verisure standards for Streamlit in Snowflake apps on compute pools. Use when creating, editing or reviewing a Streamlit app in the streamlit-governance-cicd repo (apps/<team>/<app>): scaffolds the app with app.yml, chooses owner's vs restricted caller's rights, applies the naming, connection, dependency and security rules, and runs the same checklist that blocks the pull request in GitHub Actions. Triggers: new streamlit app, create streamlit app, streamlit standards, streamlit checklist, check my app, app.yml, caller's rights app, owner's rights app, before I push my streamlit app."
---

# Streamlit app standards (Verisure)

Use this skill to help a developer build a Streamlit app that the CI/CD will accept.
The rules live in `standards.yml` (next to this file). The checklist script
`scripts/check_streamlit_app.py` applies them. **GitHub Actions runs the same script on every
pull request and blocks the merge on any error**, so a PASS here means a PASS in CI.

## Workflow

### 1. Find the context
- Work from the root of the `streamlit-governance-cicd` repo (it has `config/teams.yml`).
- Ask which **team** owns the app and read `config/teams.yml`: the team folder, the allowed
  access model (`allowed_rights`) and the warehouse. If the team is missing, stop: the platform
  team must onboard it first (`snowflake/onboard_team.sh`).
- Ask for the app name. It must be `snake_case`, 3-40 characters. This becomes the Streamlit
  object name `<DATABASE>.<TEAM>.<APP_NAME>`.

### 2. Choose the access model
| Need | rights | Connection |
| --- | --- | --- |
| Everyone sees the same data (e.g. FinOps, central reports). Viewers must NOT need data access. | `owner` | `st.connection("snowflake")` |
| Each viewer only sees their own rows (row access policies by role/country). | `caller` | `st.connection("snowflake-callers-rights")` |

Explain to the developer:
- **Owner's rights:** row access policies see the app owner role, not the viewer, so they can't filter per viewer.
- **Caller's rights:**
  - the viewer needs their own `SELECT` on the data;
  - the policy uses the viewer's **default role**, not the role selected in Snowsight;
  - the admin must have granted the caller grants at onboarding.

### 3. Scaffold `apps/<team>/<app_name>/`
- `streamlit_app.py`: the entry point.
- `requirements.txt`: exact pins only (`pandas==2.2.3`). Never list `streamlit`, because the container image has it.
- `README.md`: what the app does, the data used, and a contact.
  If a PR comment reports FAILED, fix every error listed in "How to fix" and push again: the same comment is updated.
- `app.yml`:
```yaml
name: <app_name>            # same as the folder
title: <Title shown in Snowsight>
description: <one line>
owner_email: <person responsible>
rights: owner               # or caller (must be allowed for the team)
viewers: []                 # extra roles; <TEAM>_STREAMLIT_USERS already sees every team app
```

### 4. Code rules (container runtime on a compute pool)
- Connect with `st.connection(...)`. Never use `get_active_session()` or `_snowflake`: they aren't thread-safe on a compute pool.
- No `USE ROLE` and no `USE WAREHOUSE`. The CI/CD sets the owner role and the warehouse.
- No passwords, tokens, keys or account URLs anywhere in the app folder.
- Caller's rights apps:
  - open `st.connection("snowflake-callers-rights")` at the **top of the script**, not inside a function, `if` or page, because the viewer token lasts only 2 minutes;
  - every `@st.cache_data` uses `scope="session"`, so one viewer's rows are never served to another.
- Cache expensive queries with `st.cache_data`. Select only the columns you need (`SELECT *` is a warning).
- Keep files under 1 MB and read data from Snowflake instead of shipping it in the repo.

### 5. Run the checklist (always, before every push)
From the repo root:
```bash
pip install pyyaml==6.0.2   # once
python skills/streamlit-app-standards/scripts/check_streamlit_app.py apps/<team>/<app_name> \
  --head-branch "$(git branch --show-current)" --base-branch dev
```
If the skill was installed from the catalog, the script is in this skill's folder: run it with
`--repo-root <path to the repo>`.

- **PASSED** → commit, push the branch and open the PR into `dev`.
- **FAILED** → fix every error using the "How to fix" column, then run it again. Never tell the developer to push while there are errors: the PR will be blocked with the same list.

### 6. Branch and release flow (explain once)
1. Branch from `dev`: `feature/<team>-<description>`. Open a PR into `dev`.
2. The checklist runs, and on failure the PR gets a comment with the failed items. On merge, the app is deployed to DEV automatically.
3. PR `dev` → `main`. After approval and merge, the deploy waits for the `prd` environment approval, then goes to PRD.
4. The deploy always runs as `<TEAM>_STREAMLIT_OWNER`, on the team compute pool and warehouse.

## Stopping points
- Before scaffolding: confirm the team, app name and access model.
- After the checklist: show the result. Don't continue to a push while there are errors.
