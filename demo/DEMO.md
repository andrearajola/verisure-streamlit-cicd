# Demo: develop a Streamlit app from Snowsight and from VS Code

One repo, one skill, one CI/CD. A developer can work in a **Snowsight Git workspace** or in
**VS Code**; in both, CoCo uses the skill `streamlit-app-standards` to build the app the right
way, and GitHub runs the same checklist on every PR, so nothing reaches Snowflake unchecked.

| | Act 1: Snowsight | Act 2: VS Code |
| --- | --- | --- |
| Team / role | FINANCE / `SF-SNOWFLAKETM-FINANCE-STREAMLIT-ENGINEER` | COMERCIAL / `SF-SNOWFLAKETM-COMERCIAL-STREAMLIT-ENGINEER` |
| App | `apps/finance/sales_trend` | `apps/comercial/channel_mix` |
| Story | Built **with** the skill: green PR first time | Built **without** the skill: PR blocked, CoCo + skill fix it |
| Branch | `feature/finance-sales-trend` | `feature/comercial-channel-mix` |
| Reference code | `demo/reference/finance_sales_trend.py` | `demo/reference/comercial_channel_mix_broken.py`, then `comercial_channel_mix.py` |

Act 3 (optional): change a rule in the skill and show the new version arriving by email and in CoCo.

Test data: `DB_STREAMLIT.DEMO_DATA.SALES (COUNTRY, MONTH, AMOUNT)` and
`DB_STREAMLIT.DEMO_DATA.ORDERS (REGION, CHANNEL, ORDERS, REVENUE)`.

---

## Presenting order
Deck: `Verisure_Demo_CICD_DEV_ES.html` (Spanish). Live parts in GitHub and Snowflake.

| # | What | Where |
| --- | --- | --- |
| 1 | Goal and end-to-end flow | deck sections 1-2 |
| 2 | Two ways to develop and what the PR blocks | deck sections 3-4 |
| 3 | **Part 1 live**: Snowsight, built with the skill | Snowsight + GitHub |
| 4 | **Part 2 live**: VS Code, built without the skill, then fixed | VS Code + GitHub |
| 5 | Skill CI/CD (deck section 5), then **Part 3 live** | GitHub + email |
| 6 | Roles today vs target, how the DEPLOYER is chosen, next steps | deck sections 6-9 |

Say at the start: *"Hoy enseñamos solo DEV. PRD funcionará igual, con un PR de dev a main y una aprobación en GitHub."*

## Preparation (once, before the demo)

### Snowsight
1. Switch role to `SF-SNOWFLAKETM-FINANCE-STREAMLIT-ENGINEER`.
2. **Projects » Workspaces » From Git repository**: URL
   `https://github.com/andrearajola/verisure-streamlit-cicd`, integration `GIT_GITHUB_PILOT`,
   OAuth (done).
3. Check that the role sees what the demo needs:
   ```sql
   SHOW STREAMLITS IN SCHEMA DB_STREAMLIT.FINANCE;            -- SALES_BY_COUNTRY, MARGIN_BY_COUNTRY
   SELECT * FROM DB_STREAMLIT.DEMO_DATA.SALES LIMIT 5;        -- test data
   SHOW CORTEX EXTENSIONS IN SCHEMA DB_STREAMLIT.SKILLS_DEV;  -- the skill
   ```
4. Open one existing app (`MARGIN_BY_COUNTRY`) once, so the compute pool is warm.
5. Open CoCo in the workspace and type `/streamlit` to confirm the skill shows up. If it doesn't,
   attach the file instead: `@skills/streamlit-app-standards/SKILL.md` (same content, it's in the repo).

### VS Code
1. Clone the repo with HTTPS:
   ```bash
   git clone https://andrearajola@github.com/andrearajola/verisure-streamlit-cicd.git
   cd verisure-streamlit-cicd && git checkout dev
   python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
   ```
2. Open the folder in VS Code (accept the recommended extensions: Python, Snowflake).
3. Open CoCo (Cortex Code) in the VS Code terminal, in the repo folder. Check that `/streamlit-app-standards`
   is available, or attach `@skills/streamlit-app-standards/SKILL.md`.
4. Dry run the local checklist once:
   ```bash
   python skills/streamlit-app-standards/scripts/check_streamlit_app.py apps/comercial/orders_overview
   ```

### GitHub (browser tabs)
- PR list: https://github.com/andrearajola/verisure-streamlit-cicd/pulls
- Actions: https://github.com/andrearajola/verisure-streamlit-cicd/actions
- Your inbox (skill emails, Act 3)

---

## Act 1: Snowsight, built with the skill

**Message:** "A FINANCE engineer never leaves Snowsight. CoCo knows our rules because of the skill."

*Qué decir:* "El ingeniero de FINANCE trabaja solo en Snowsight. CoCo conoce nuestras reglas gracias a la skill, así que la app sale bien a la primera."

1. In the Git workspace, create branch **`feature/finance-sales-trend`** from `dev`.
2. Ask CoCo:
   > /streamlit-app-standards Create a new FINANCE app called sales_trend that shows monthly sales
   > per country from DB_STREAMLIT.DEMO_DATA.SALES, with a country filter, two KPIs and a line chart.
   > Only create the files; don't deploy it.
3. Show what CoCo does because of the skill:
   - asks/confirms team, name and access model (owner's rights);
   - creates the 6 files: `streamlit_app.py`, `app.yml`, `snowflake.yml`, `pyproject.toml` (no dependencies),
     `.streamlit/config.toml`, `README.md`;
   - the folder becomes a Snowsight Streamlit project: open `streamlit_app.py` and press **Run** to try it
     (a private development app, nothing is deployed). *"Lo puede probar, pero no desplegar."*
   - uses `st.connection("snowflake")`, `@st.cache_data`, named columns, no `USE ROLE`;
   - **does not deploy**: it stops and says to push and open the PR (the engineer role can't create apps).
   Backup if CoCo's result differs a lot: copy the 6 files from `demo/reference/apps/finance/sales_trend/`.
4. Commit and push from the workspace. In GitHub, open the PR into `dev`.
5. **PR comment: PASSED**, checks `app-checks` and `skill-checks` green.
6. Merge. Show **Actions » Deploy Streamlit apps**: OIDC login (no secrets), app created,
   access granted to the FINANCE engineer role, verify OK.
7. Back in Snowsight: **Projects » Streamlit » SALES_TREND**. Open it.

**Takeaway:** the developer got it right the first time because the rules travel with CoCo.

*Qué decir al ver el deploy:* "GitHub entra en Snowflake sin contraseñas (OIDC), crea la app en el schema de FINANCE y comprueba que todo está como debe. El ingeniero no puede crear apps: solo el CI/CD."

---

## Act 2: VS Code, built without the skill

**Message:** "Not everyone uses the skill. The CI/CD makes sure that doesn't matter."

*Qué decir:* "No todo el mundo usará la skill. Da igual: el PR aplica las mismas reglas y no deja hacer merge hasta que están bien."

1. In VS Code: `git checkout dev && git pull && git checkout -b feature/comercial-channel-mix`.
2. Create `apps/comercial/channel_mix/` "the old way" (copied from a notebook):
   - `streamlit_app.py`: paste `demo/reference/comercial_channel_mix_broken.py`
   - `requirements.txt`: `plotly` (and no `snowflake.yml` / `pyproject.toml`)
   - `app.yml`:
     ```yaml
     name: channel_mix
     title: Channel mix
     rights: owner
     ```
3. Commit, push, open the PR into `dev`.
4. **PR comment: FAILED, 6 errors, merge blocked.** Walk through the "How to fix" column:
   `get_active_session`, `USE WAREHOUSE`, `plotly` / `requirements.txt` (no PyPI access, use
   `pyproject.toml`), missing `owner_email` / `description`, no `st.connection`, no `snowflake.yml`.
   Try **Merge**: GitHub refuses.
5. Ask CoCo in the VS Code terminal:
   > /streamlit-app-standards My PR for apps/comercial/channel_mix failed. Fix it and run the checklist. Don't deploy.
6. Show CoCo rewriting the app (plotly → `st.bar_chart`), deleting `requirements.txt`, adding
   `pyproject.toml`, `snowflake.yml`, `.streamlit/config.toml` and `README.md`, completing `app.yml`,
   and running the checklist locally until **PASSED**.
   Backup: `rm apps/comercial/channel_mix/requirements.txt && cp -R demo/reference/apps/comercial/channel_mix/. apps/comercial/channel_mix/`
7. Push to the same branch. **The same PR comment changes to PASSED.** Merge, deploy, open
   `DB_STREAMLIT.COMERCIAL.CHANNEL_MIX` in Snowsight.

**Takeaway:** same rules locally, in CoCo and in GitHub. Bad code can't reach Snowflake.

*Qué decir:* "Las mismas reglas en local, en CoCo y en GitHub. El código que no cumple no llega a Snowflake."

---

## Act 3 (optional): the skill has its own CI/CD

**Message:** "When the platform team changes a rule, every developer gets it automatically."

*Qué decir:* "La skill también tiene CI/CD. Cuando el equipo de plataforma cambia una regla, todos los desarrolladores la reciben solos, y nos llega un email."

1. Branch `feature/platform-skill-demo` from `dev`. Small, safe change: in
   `skills/streamlit-app-standards/standards.yml`, reword the `fix:` text of `APP018`
   (for example add "Name the columns, e.g. SELECT country, amount").
   Push and open the PR: `skill-checks` and `app-checks` re-check every app.
2. Merge. **Actions » Sync skills**: new version published, `READ` granted to the engineer roles.
3. Show the **email** (what changed, version, commit).
4. Re-open CoCo (Snowsight or VS Code): the new version is the one in use.

---

---

## Close: roles (deck sections 6-9)
*Qué decir:*
- "Hoy, para empezar rápido, un solo rol de plataforma (`STREAMLIT_CICD_DEV`) es dueño de todo. Los equipos solo tienen el rol de ingeniero."
- "El modelo objetivo, acordado con Manuel: por dominio, DEPLOYER (dueño del schema, solo el CI/CD), que hereda ENGINEER (desarrollar), que hereda el rol analyst que el equipo ya tiene. Todo cuelga de DBA."
- "Las apps se comparten una a una con el rol analyst de cada equipo, en `app.yml`."
- "El CI/CD no necesita una lista de roles: la carpeta de la app da el schema, y el dueño del schema es el DEPLOYER."
- Open point: scope of `CALLER DATA READ` (account vs database).

## After the demo (reset)
- To show it again, delete the two apps with a PR that removes their folders, then drop them
  (the pipeline role owns them): `DROP STREAMLIT DB_STREAMLIT.FINANCE.SALES_TREND;`
  `DROP STREAMLIT DB_STREAMLIT.COMERCIAL.CHANNEL_MIX;`
- Delete the feature branches in GitHub.
