#!/usr/bin/env python3
"""Upload skills/ to the skill stage and run the Snowflake skill sync (DEV).

  sync_skills.py --env dev --commit <sha>

Runs as the environment's deploy_role (config/envs.yml), on the team warehouse of the first team.
Release emails go to envs.yml skill_notify (addresses must be in SKILLS_EMAIL_INT ALLOWED_RECIPIENTS).
Same connection rules as deploy_app.py (SNOW_CONN_ARGS, default -x). Exit 1 if any skill FAILED.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_app import Snow, ident, load_yaml, sql_str  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--commit", required=True)
    a = ap.parse_args()
    if not re.fullmatch(r"[0-9a-f]{7,40}", a.commit):
        sys.exit(f"invalid commit {a.commit}")
    envs = load_yaml(ROOT / "config/envs.yml")
    if a.env not in envs:
        sys.exit(f"unknown environment {a.env!r} (config/envs.yml has {list(envs)})")
    env = envs[a.env]
    branch = env["branch"]
    db = ident(env["database"], "database")
    role = ident(env["deploy_role"], "deploy role")
    wh = ident(env.get("skill_warehouse") or next(iter(load_yaml(ROOT / "config/teams.yml").values()))["warehouse"],
               "warehouse")
    notify = [str(e).strip() for e in (env.get("skill_notify") or [])]
    bad = [e for e in notify if not EMAIL.match(e)]
    if bad:
        sys.exit(f"invalid email address in skill_notify: {bad}")

    snow = Snow(role, wh)
    stage = f"@{db}.SKILLS_CICD.SKILL_SRC/{branch}"
    files = [p for p in sorted((ROOT / "skills").rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    stmts = [f"REMOVE {stage}/;"]  # deleted files in git must disappear from the stage
    for p in files:
        rel = p.parent.relative_to(ROOT).as_posix()
        stmts.append(f"PUT {sql_str('file://' + p.as_posix())} {stage}/{rel}/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;")
    snow.run("\n".join(stmts))
    print(f"uploaded {len(files)} files to {stage}")

    rows = snow.run(f"CALL {db}.SKILLS_CICD.SP_SKILL_SYNC_ALL({sql_str(branch)}, {sql_str(a.commit)}, "
                    f"{sql_str(','.join(notify))});")
    out = next(iter(rows[0].values())) if rows else "no result"
    print(out)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### Skill sync ({branch} @ {a.commit[:7]})\n```\n{out}\n```\n")
    return 1 if "FAILED" in out else 0


if __name__ == "__main__":
    sys.exit(main())
