#!/usr/bin/env python3
"""Streamlit app standards checklist (deterministic).

Same script, two callers:
  - the streamlit-app-standards skill (CoCo runs it while the developer works)
  - GitHub Actions on every pull request (required check: any error blocks the merge)

Usage:
  check_streamlit_app.py [--repo-root DIR] [--head-branch B --base-branch B]
                         [--markdown OUT.md] [--json OUT.json] [APP_DIR ...]
Exit code: 0 = no errors (warnings allowed), 1 = at least one error, 2 = bad usage.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required: pip install pyyaml")

HERE = Path(__file__).resolve().parent
DEFAULT_STANDARDS = HERE.parent / "standards.yml"
REPORT_MARKER = "<!-- streamlit-standards-report -->"

APP_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
ROLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?==[A-Za-z0-9.!+*_-]+(\s*;.*)?$")
CONN_RE = re.compile(r"""st\.connection\(\s*["']snowflake(-callers-rights)?["']""")
SECRET_PATTERNS = [
    (re.compile(r"""(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*["'][^"'\s]{4,}["']"""), "credential assigned in code"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)\b[a-z0-9_-]+(\.[a-z0-9_-]+)*\.snowflakecomputing\.com\b"), "Snowflake account URL"),
    (re.compile(r"\b(ghp_|github_pat_|xox[bp]-)[A-Za-z0-9_]{10,}"), "access token"),
]
TEXT_SUFFIXES = {".py", ".txt", ".toml", ".yml", ".yaml", ".json", ".cfg", ".ini", ".sql", ".md", ".env"}
BLOCKING_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If, ast.For, ast.AsyncFor,
                  ast.While, ast.With, ast.AsyncWith, ast.Try)


@dataclass
class Finding:
    rule: str
    title: str
    severity: str
    app: str
    details: list[str] = field(default_factory=list)
    fix: str = ""


class Checker:
    def __init__(self, repo_root: Path, standards: dict, teams: dict):
        self.root = repo_root
        self.rules = standards.get("rules", {})
        self.teams = teams or {}
        self.by_folder = {str(v.get("folder", k)).lower(): (k, v) for k, v in self.teams.items()}
        self.findings: list[Finding] = []
        self.checked: list[str] = []
        self.passed = 0

    # -- helpers -------------------------------------------------------
    def rule(self, rid: str) -> dict:
        return self.rules.get(rid, {})

    def enabled(self, rid: str) -> bool:
        return self.rule(rid).get("enabled", True)

    def report(self, rid: str, app: str, details: list[str], severity: str | None = None) -> None:
        if not self.enabled(rid):
            return
        if not details:
            self.passed += 1
            return
        r = self.rule(rid)
        self.findings.append(Finding(rid, r.get("title", rid), severity or r.get("severity", "error"),
                                     app, details, r.get("fix", "")))

    # -- branch --------------------------------------------------------
    def check_branch(self, head: str, base: str) -> None:
        if not head or not base:
            return
        r = self.rule("BR001")
        prefixes = r.get("feature_prefixes", ["feature", "fix"])
        scopes = set(self.by_folder) | {str(s).lower() for s in r.get("platform_scopes", ["platform"])}
        details: list[str] = []
        if base == "dev":
            if head == "main" and r.get("sync_from_main", True):
                pass  # sync dev with main after a release
            else:
                m = re.match(r"^(%s)/([a-z0-9]+)-[a-z0-9][a-z0-9-]*$" % "|".join(map(re.escape, prefixes)), head)
                if not m:
                    details.append(f"branch '{head}' does not match <{'|'.join(prefixes)}>/<team>-<description> (lowercase, '-' separated)")
                elif m.group(2) not in scopes:
                    details.append(f"branch '{head}': '{m.group(2)}' is not a team in config/teams.yml (or a platform scope)")
        elif base == "main" and head != "dev":
            details.append(f"pull requests into main must come from dev, not '{head}'")
        self.report("BR001", "(branch)", details)

    # -- app -----------------------------------------------------------
    def check_app(self, app_dir: Path) -> None:
        try:
            rel = app_dir.resolve().relative_to(self.root)
        except ValueError:
            rel = app_dir
        label = rel.as_posix()
        self.checked.append(label)
        parts = rel.parts

        # APP001 path shape
        d = []
        if len(parts) != 3 or parts[0] != "apps":
            d.append(f"path is '{label}', expected apps/<team>/<app_name>")
        elif not APP_NAME_RE.match(parts[2]):
            d.append(f"app folder '{parts[2]}' is not snake_case (a-z, 0-9, _; 3-40 chars, starts with a letter)")
        self.report("APP001", label, d)

        # APP002 team
        team_key, team_cfg = None, {}
        folder = parts[1] if len(parts) >= 2 else ""
        if folder.lower() in self.by_folder:
            team_key, team_cfg = self.by_folder[folder.lower()]
            self.report("APP002", label, [])
        else:
            self.report("APP002", label, [f"team folder '{folder}' not found in config/teams.yml (known: {', '.join(sorted(self.by_folder)) or 'none'})"])

        # APP003 app.yml
        meta: dict = {}
        app_yml = app_dir / "app.yml"
        if not app_yml.is_file():
            self.report("APP003", label, ["app.yml not found"])
        else:
            try:
                loaded = yaml.safe_load(app_yml.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("top level must be a mapping (key: value)")
                meta = loaded
                self.report("APP003", label, [])
            except Exception as exc:  # noqa: BLE001
                self.report("APP003", label, [f"app.yml is not valid: {exc}"])

        if meta:
            required = self.rule("APP004").get("required", ["name", "title", "description", "owner_email", "rights"])
            missing = [k for k in required if not str(meta.get(k) or "").strip()]
            self.report("APP004", label, [f"missing or empty: {', '.join(missing)}"] if missing else [])

            name = str(meta.get("name") or "")
            self.report("APP005", label, [] if not name or name == app_dir.name else
                        [f"name is '{name}' but the folder is '{app_dir.name}'"])

            rights = str(meta.get("rights") or "").strip().lower()
            allowed = [str(x).lower() for x in (team_cfg.get("allowed_rights") or ["owner", "caller"])]
            d = []
            if rights and rights not in ("owner", "caller"):
                d.append(f"rights is '{rights}', must be owner or caller")
            elif rights and team_key and rights not in allowed:
                d.append(f"team {team_key} allows rights {allowed}, app uses '{rights}'")
            self.report("APP006", label, d)

            email = str(meta.get("owner_email") or "")
            self.report("APP007", label, [] if not email or EMAIL_RE.match(email) else [f"'{email}' is not a valid email"])

            viewers = meta.get("viewers") or []
            d = []
            if not isinstance(viewers, list):
                d.append("viewers must be a list of role names")
            else:
                d += [f"'{v}' is not a valid role name" for v in viewers if not ROLE_RE.match(str(v))]
            self.report("APP008", label, d)
        rights = str(meta.get("rights") or "").strip().lower()

        # APP009 entry point
        main = app_dir / "streamlit_app.py"
        self.report("APP009", label, [] if main.is_file() else ["streamlit_app.py not found"])

        # APP010 requirements
        req = app_dir / "requirements.txt"
        d = []
        if not req.is_file():
            d.append("requirements.txt not found")
        else:
            for n, raw in enumerate(req.read_text(encoding="utf-8").splitlines(), 1):
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                pkg = re.split(r"[\[=<>!~; ]", line, maxsplit=1)[0].lower()
                if pkg == "streamlit":
                    d.append(f"line {n}: do not list streamlit (the container runtime provides it)")
                elif not PIN_RE.match(line):
                    d.append(f"line {n}: '{line}' is not pinned with ==")
        self.report("APP010", label, d)

        # Source scan
        files = [p for p in sorted(app_dir.rglob("*")) if p.is_file()]
        py_files = [p for p in files if p.suffix == ".py"]
        py_src = {p: p.read_text(encoding="utf-8", errors="replace") for p in py_files}

        d = []
        for p, src in py_src.items():
            for n, line in enumerate(src.splitlines(), 1):
                if "get_active_session" in line:
                    d.append(f"{p.name}:{n}: get_active_session")
                if re.match(r"^\s*(import\s+_snowflake|from\s+_snowflake\s+import)", line):
                    d.append(f"{p.name}:{n}: _snowflake module")
        self.report("APP011", label, d)

        d = [f"{p.name}:{n}: {m.group(0)}" for p, src in py_src.items()
             for n, line in enumerate(src.splitlines(), 1)
             for m in [re.search(r"(?i)\bUSE\s+(SECONDARY\s+)?(ROLE|WAREHOUSE)\b", line)] if m and not m.group(1)]
        self.report("APP012", label, d)

        d = []
        for p in files:
            if p.suffix.lower() not in TEXT_SUFFIXES or p.stat().st_size > 1024 * 1024:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for n, line in enumerate(text.splitlines(), 1):
                for rx, what in SECRET_PATTERNS:
                    if rx.search(line):
                        d.append(f"{p.relative_to(app_dir).as_posix()}:{n}: {what}")
        self.report("APP013", label, d)

        uses_conn = any(CONN_RE.search(src) for src in py_src.values())
        self.report("APP014", label, [] if uses_conn or not py_src else ["no st.connection(\"snowflake\") found"])

        self.report("APP015", label, self._callers_rights(rights, main, py_src))

        self.report("APP016", label, [] if (app_dir / "README.md").is_file() else ["README.md not found"])

        r17 = self.rule("APP017")
        max_file, max_total = r17.get("max_file_kb", 1024) * 1024, r17.get("max_total_kb", 10240) * 1024
        d = [f"{p.relative_to(app_dir).as_posix()} is {p.stat().st_size // 1024} KB"
             for p in files if p.stat().st_size > max_file]
        total = sum(p.stat().st_size for p in files)
        if total > max_total:
            d.append(f"app is {total // 1024} KB in total")
        self.report("APP017", label, d)

        d = [f"{p.name}:{n}" for p, src in py_src.items()
             for n, line in enumerate(src.splitlines(), 1) if re.search(r"(?i)\bselect\s+\*", line)]
        self.report("APP018", label, d)

    def _callers_rights(self, rights: str, main: Path, py_src: dict) -> list[str]:
        uses_callers = any("snowflake-callers-rights" in s for s in py_src.values())
        if rights != "caller":
            return ["app uses st.connection(\"snowflake-callers-rights\") but rights is not caller"] if uses_callers else []
        d: list[str] = []
        if main not in py_src or "snowflake-callers-rights" not in py_src[main]:
            d.append("rights is caller but streamlit_app.py does not open st.connection(\"snowflake-callers-rights\")")
        for p, src in py_src.items():
            try:
                tree = ast.parse(src)
            except SyntaxError as exc:
                d.append(f"{p.name}: syntax error line {exc.lineno}")
                continue
            parents = {}
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    parents[child] = node
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "connection"
                        and node.args and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "snowflake-callers-rights"):
                    anc = parents.get(node)
                    while anc is not None and not isinstance(anc, BLOCKING_NODES):
                        anc = parents.get(anc)
                    if anc is not None:
                        d.append(f"{p.name}:{node.lineno}: caller's-rights connection is inside a "
                                 f"{type(anc).__name__.replace('Def', '').lower()} block, open it at the top of the script")
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for dec in node.decorator_list:
                        target = dec.func if isinstance(dec, ast.Call) else dec
                        if isinstance(target, ast.Attribute) and target.attr == "cache_data":
                            scope = None
                            if isinstance(dec, ast.Call):
                                scope = next((k.value.value for k in dec.keywords
                                              if k.arg == "scope" and isinstance(k.value, ast.Constant)), None)
                            if scope != "session":
                                d.append(f"{p.name}:{dec.lineno}: @st.cache_data on '{node.name}' needs scope=\"session\" in a caller's-rights app")
        return d

    # -- output --------------------------------------------------------
    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity != "error"]

    def markdown(self) -> str:
        ok = not self.errors
        lines = [REPORT_MARKER,
                 f"## Streamlit standards: {'PASSED' if ok else 'FAILED'}",
                 "",
                 f"Apps checked: {', '.join(f'`{a}`' for a in self.checked) or 'none (no app changed)'}  ",
                 f"Errors: **{len(self.errors)}** | Warnings: {len(self.warnings)} | Checks passed: {self.passed}",
                 ""]
        if not ok:
            lines.append("This pull request is **blocked** until every error below is fixed. "
                         "Run the checklist locally with the `streamlit-app-standards` skill to see the same result.")
            lines.append("")
        for title, items in (("Errors (block the merge)", self.errors), ("Warnings", self.warnings)):
            if not items:
                continue
            lines += [f"### {title}", "", "| Rule | App | What failed | How to fix |", "| --- | --- | --- | --- |"]
            for f in items:
                what = "<br>".join(x.replace("|", "\\|") for x in f.details)
                lines.append(f"| {f.rule} {f.title} | `{f.app}` | {what} | {f.fix.replace('|', '/')} |")
            lines.append("")
        return "\n".join(lines)

    def as_json(self) -> dict:
        return {"passed": not self.errors, "apps": self.checked, "checks_passed": self.passed,
                "errors": [asdict(f) for f in self.errors], "warnings": [asdict(f) for f in self.warnings]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("apps", nargs="*", help="app folders (apps/<team>/<app_name>)")
    ap.add_argument("--repo-root", default=".", help="repository root (contains config/teams.yml)")
    ap.add_argument("--standards", default=str(DEFAULT_STANDARDS))
    ap.add_argument("--head-branch", default="")
    ap.add_argument("--base-branch", default="")
    ap.add_argument("--markdown")
    ap.add_argument("--json")
    a = ap.parse_args(argv)

    root = Path(a.repo_root).resolve()
    teams_file = root / "config" / "teams.yml"
    if not teams_file.is_file():
        print(f"config/teams.yml not found under {root}", file=sys.stderr)
        return 2
    standards = yaml.safe_load(Path(a.standards).read_text(encoding="utf-8")) or {}
    chk = Checker(root, standards, yaml.safe_load(teams_file.read_text(encoding="utf-8")) or {})
    chk.check_branch(a.head_branch, a.base_branch)
    for app in a.apps:
        p = Path(app)
        p = p if p.is_absolute() else root / p
        if not p.is_dir():
            print(f"skipping {app}: not a folder (deleted?)", file=sys.stderr)
            continue
        chk.check_app(p)

    md = chk.markdown()
    print(md)
    if a.markdown:
        Path(a.markdown).write_text(md + "\n", encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(chk.as_json(), indent=2), encoding="utf-8")
    return 1 if chk.errors else 0


if __name__ == "__main__":
    sys.exit(main())
