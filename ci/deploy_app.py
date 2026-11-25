#!/usr/bin/env python3
"""Deploy one Streamlit app to one environment.

  deploy_app.py --env dev|prd --app apps/<team>/<app_name> --commit <sha> [--verify-only]

- Re-runs the standards checklist (defence in depth: a push that skipped the PR still can't deploy).
- Deploys AS the role that will own the app (ownership of a Streamlit app can't be transferred):
  <TEAM>_STREAMLIT_OWNER<suffix> by default, or one shared role (envs.yml deploy_role).
- First deploy: CREATE STREAMLIT on the compute pool + warehouse (container runtime).
  Next deploys: new live version in place, so the URL and the grants are kept.
- Grants USAGE to the viewers in app.yml (the team USERS role gets it through a future grant).
- Verifies owner, compute pool, warehouse, runtime, commit and grants; exits 1 on any mismatch.

Optional settings per environment in config/envs.yml (default = one role and one pool per team):
  deploy_role    one role creates and owns every app (no per-team OWNER / USERS roles)
  compute_pool   one compute pool shared by every app
  pypi_eai       external access integration for PyPI; "" = none (requirements.txt must be empty)
  create_schema  true = the deploy role creates the team schema and stage if missing

Snowflake connection: SNOW_CONN_ARGS (default "-x": temporary connection from SNOWFLAKE_* env vars,
which snowflakedb/snowflake-actions sets with OIDC). Locally: SNOW_CONN_ARGS="-c <connection>".
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "skills" / "streamlit-app-standards" / "scripts" / "check_streamlit_app.py"
RUNTIME = "SYSTEM$ST_CONTAINER_RUNTIME_PY3_11"
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
SUMMARY: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    SUMMARY.append(msg)


def ident(value: str, what: str) -> str:
    if not IDENT.match(value or ""):
        sys.exit(f"invalid {what}: {value!r}")
    return value.upper()


def sql_str(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


class Snow:
    def __init__(self, role: str, warehouse: str):
        self.base = ["snow", "sql", *shlex.split(os.environ.get("SNOW_CONN_ARGS", "-x")),
                     "--role", role, "--warehouse", warehouse, "--format", "json"]

    def run(self, sql: str, check: bool = True):
        """Run one or more statements; returns the rows of the LAST statement."""
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
            f.write(sql)
            path = f.name
        try:
            p = subprocess.run(self.base + ["-f", path], capture_output=True, text=True)
        finally:
            os.unlink(path)
        if p.returncode != 0:
            if check:
                print(p.stdout[-4000:], p.stderr[-4000:], sep="\n", file=sys.stderr)
                raise RuntimeError(f"snow sql failed:\n{sql}")
            return None
        out = p.stdout.strip()
        start = min([i for i in (out.find("["), out.find("{")) if i >= 0], default=-1)
        data = json.loads(out[start:]) if start >= 0 else []
        if data and isinstance(data[0], list):  # multi-statement output: one list per statement
            data = data[-1]
        return data


def load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def run_checklist(app_dir: Path) -> None:
    spec = importlib.util.spec_from_file_location("check_streamlit_app", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_streamlit_app"] = mod
    spec.loader.exec_module(mod)
    rc = mod.main(["--repo-root", str(ROOT), str(app_dir)])
    if rc != 0:
        sys.exit("standards checklist FAILED: not deploying (see the report above)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--app", required=True, help="apps/<team folder>/<app_name>")
    ap.add_argument("--commit", default=os.environ.get("GITHUB_SHA", "local"))
    ap.add_argument("--verify-only", action="store_true")
    a = ap.parse_args()

    envs, teams = load_yaml(ROOT / "config/envs.yml"), load_yaml(ROOT / "config/teams.yml")
    if a.env not in envs:
        sys.exit(f"unknown environment {a.env!r} (config/envs.yml has {list(envs)})")
    env = envs[a.env]
    app_dir = (ROOT / a.app).resolve()
    parts = app_dir.relative_to(ROOT).parts
    if len(parts) != 3 or parts[0] != "apps" or not app_dir.is_dir():
        sys.exit(f"--app must be an existing apps/<team>/<app_name> folder, got {a.app}")
    by_folder = {str(v.get("folder", k)).lower(): (k, v) for k, v in teams.items()}
    if parts[1].lower() not in by_folder:
        sys.exit(f"team folder {parts[1]!r} is not in config/teams.yml: refusing to deploy")
    team, team_cfg = by_folder[parts[1].lower()]
    meta = load_yaml(app_dir / "app.yml")

    sfx = env.get("role_suffix") or ""
    db = ident(env["database"], "database")
    team = ident(team, "team")
    app = ident(meta.get("name", ""), "app name")
    if env.get("deploy_role"):
        owner_role, users_role = ident(env["deploy_role"], "deploy role"), None
    else:
        owner_role = ident(f"{team}_STREAMLIT_OWNER{sfx}", "owner role")
        users_role = ident(f"{team}_STREAMLIT_USERS{sfx}", "users role")
    pool = ident(env.get("compute_pool") or f"{team}_STREAMLIT_POOL{sfx}", "compute pool")
    wh = ident(meta.get("warehouse") or team_cfg["warehouse"], "warehouse")
    eai_name = env.get("pypi_eai", "STREAMLIT_PYPI_EAI")
    eai = ident(eai_name, "integration") if eai_name else None
    if not eai and a.verify_only is False and _has_packages(app_dir):
        sys.exit(f"{a.env} has no PyPI access (envs.yml pypi_eai is empty): requirements.txt must be empty")
    viewers = [ident(str(v), "viewer role") for v in (meta.get("viewers") or [])]
    rights = str(meta.get("rights", "owner")).lower()
    commit = re.sub(r"[^0-9a-zA-Z]", "", a.commit)[:40] or "local"
    fqn = f"{db}.{team}.{app}"
    snow = Snow(owner_role, wh)

    log(f"### Deploy `{fqn}` ({a.env})")
    log(f"- team `{team}` | rights `{rights}` | owner role `{owner_role}` | pool `{pool}` | warehouse `{wh}` | commit `{commit[:7]}`")

    if not a.verify_only:
        run_checklist(app_dir)
        if env.get("create_schema"):
            snow.run(f"CREATE SCHEMA IF NOT EXISTS {db}.{team};\nCREATE STAGE IF NOT EXISTS {db}.{team}.APP_SRC;")
        deploy(snow, app_dir, fqn, db, team, app, pool, wh, eai, viewers, meta, rights, commit)
    problems = verify(snow, fqn, db, team, app, owner_role, users_role, pool, wh, viewers, rights, commit,
                      check_commit=not a.verify_only)
    if problems:
        log("- **VERIFY FAILED**")
        for p in problems:
            log(f"  - {p}")
    else:
        log("- verify: owner, compute pool, warehouse, runtime, commit and grants OK")
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("\n".join(SUMMARY) + "\n\n")
    return 1 if problems else 0


def _has_packages(app_dir: Path) -> bool:
    req = app_dir / "requirements.txt"
    if not req.exists():
        return False
    return any(l.split("#")[0].strip() for l in req.read_text(encoding="utf-8").splitlines())


def deploy(snow, app_dir, fqn, db, team, app, pool, wh, eai, viewers, meta, rights, commit) -> None:
    # 1. Upload this commit's files to the team stage (one folder per app and commit)
    stage = f"@{db}.{team}.APP_SRC/{app.lower()}/{commit[:12]}"
    files = [p for p in sorted(app_dir.rglob("*")) if p.is_file()]
    stmts = [f"REMOVE {stage}/;"]
    for p in files:
        sub = p.parent.relative_to(app_dir).as_posix()
        target = stage if sub == "." else f"{stage}/{sub}"
        stmts.append(f"PUT {sql_str('file://' + p.as_posix())} {target}/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;")
    snow.run("\n".join(stmts))
    log(f"- uploaded {len(files)} files to `{stage}`")

    title = str(meta.get("title") or app)[:200]
    comment = f"team={team}; rights={rights}; commit={commit}; owner={meta.get('owner_email', '')}; deployed_by=ci-cd"
    exists = snow.run(f"SHOW STREAMLITS LIKE {sql_str(app)} IN SCHEMA {db}.{team};")
    eai_prop = f"EXTERNAL_ACCESS_INTEGRATIONS = ({eai}) " if eai else ""
    props = (f"QUERY_WAREHOUSE = {wh} RUNTIME_NAME = '{RUNTIME}' COMPUTE_POOL = {pool} "
             f"{eai_prop}TITLE = {sql_str(title)} COMMENT = {sql_str(comment)}")
    if not exists:
        # 2a. First deploy
        snow.run(f"CREATE STREAMLIT {fqn} FROM '{stage}' MAIN_FILE = 'streamlit_app.py' {props};")
        log("- created the app (first deploy)")
    else:
        # 2b. Update in place: same object, same URL, grants kept. Abort a live version left by a failed run.
        snow.run(f"ALTER STREAMLIT {fqn} ABORT;", check=False)
        snow.run("\n".join([
            f"ALTER STREAMLIT {fqn} ADD LIVE VERSION FROM LAST;",
            f"REMOVE 'snow://streamlit/{fqn}/versions/live/';",
            f"COPY FILES INTO 'snow://streamlit/{fqn}/versions/live/' FROM '{stage}/';",
            f"ALTER STREAMLIT {fqn} COMMIT;",
            f"ALTER STREAMLIT {fqn} SET {props};",
        ]))
        log("- updated the app in place (new version, same URL, grants kept)")

    # 3. Extra viewers from app.yml
    for v in viewers:
        snow.run(f"GRANT USAGE ON STREAMLIT {fqn} TO ROLE {v};")
    if viewers:
        log(f"- granted USAGE to {', '.join(viewers)}")


def verify(snow, fqn, db, team, app, owner_role, users_role, pool, wh, viewers, rights, commit, check_commit) -> list[str]:
    problems = []
    rows = snow.run(f"SHOW STREAMLITS LIKE {sql_str(app)} IN SCHEMA {db}.{team};")
    if not rows:
        return [f"{fqn} not found"]
    if rows[0].get("owner") != owner_role:
        problems.append(f"owner is {rows[0].get('owner')}, expected {owner_role}")
    d = (snow.run(f"DESCRIBE STREAMLIT {fqn};") or [{}])[0]
    if (d.get("compute_pool") or "").upper() != pool:
        problems.append(f"compute pool is {d.get('compute_pool')}, expected {pool}")
    if (d.get("query_warehouse") or "").upper() != wh:
        problems.append(f"query warehouse is {d.get('query_warehouse')}, expected {wh}")
    if "CONTAINER_RUNTIME" not in (d.get("runtime_name") or "").upper():
        problems.append(f"runtime is {d.get('runtime_name')}, expected {RUNTIME}")
    if check_commit and f"commit={commit};" not in (d.get("comment") or ""):
        problems.append(f"comment does not carry commit {commit[:7]}: {d.get('comment')}")
    grants = snow.run(f"SHOW GRANTS ON STREAMLIT {fqn};") or []
    usage = {g.get("grantee_name") for g in grants if g.get("privilege") == "USAGE"}
    for r in [*([users_role] if users_role else []), *viewers]:
        if r not in usage:
            problems.append(f"role {r} has no USAGE on the app")
    if rights == "caller":
        # SHOW CALLER GRANTS only lists objects the role itself has a privilege on. The owner role has
        # no SELECT on the data (by design), so it only sees its warehouse caller grant, which
        # onboard_team.sh ... caller grants together with the data caller grants.
        cg = snow.run(f"SHOW CALLER GRANTS TO ROLE {owner_role};", check=False) or []
        if not any(g.get("granted_on") == "WAREHOUSE" and (g.get("name") or "").upper() == wh for g in cg):
            problems.append(f"rights=caller but {owner_role} has no caller grants (warehouse {wh}): "
                            "ask the admin to run onboard_team.sh ... caller")
    return problems


if __name__ == "__main__":
    sys.exit(main())
