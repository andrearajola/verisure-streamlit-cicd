"""Unit tests for the Streamlit standards checklist: every rule has a passing and a failing case."""
import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "skills" / "streamlit-app-standards" / "scripts" / "check_streamlit_app.py"
spec = importlib.util.spec_from_file_location("check_streamlit_app", SCRIPT)
chk = importlib.util.module_from_spec(spec)
sys.modules["check_streamlit_app"] = chk  # dataclasses look the module up while the class is built
spec.loader.exec_module(chk)

GOOD_CALLER_APP = '''\
import streamlit as st
callers = st.connection("snowflake-callers-rights")

@st.cache_data(ttl=60, scope="session")
def load():
    return callers.query("SELECT country, amount FROM T")

st.dataframe(load())
'''
GOOD_OWNER_APP = '''\
import streamlit as st
conn = st.connection("snowflake")
st.dataframe(conn.query("SELECT a FROM T"))
'''


# Fixed teams for the rule tests (independent of the real config/teams.yml)
TEST_TEAMS = """\
FINANCE:
  folder: finance
  allowed_rights: [caller]
  warehouse: FINANCE_WH
COMERCIAL:
  folder: comercial
  allowed_rights: [owner]
  warehouse: COMERCIAL_WH
"""


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "teams.yml").write_text(TEST_TEAMS)
    return tmp_path


def make_app(root: Path, team="finance", name="good_app", rights="caller", code=None,
             req="pandas==2.2.3\n", app_yml=None, readme=True, extra=None) -> Path:
    d = root / "apps" / team / name
    d.mkdir(parents=True)
    if code is not False:
        (d / "streamlit_app.py").write_text(code if code is not None else
                                            (GOOD_CALLER_APP if rights == "caller" else GOOD_OWNER_APP))
    if req is not None:
        (d / "requirements.txt").write_text(req)
    if app_yml is None:
        app_yml = textwrap.dedent(f"""\
            name: {name}
            title: Test app
            description: Test
            owner_email: someone@verisure.com
            rights: {rights}
            viewers: []
            """)
    if app_yml is not False:
        (d / "app.yml").write_text(app_yml)
    if readme:
        (d / "README.md").write_text("# test\n")
    for rel, content in (extra or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content) if isinstance(content, bytes) else p.write_text(content)
    return d


def run(root: Path, apps=(), head="", base=""):
    args = ["--repo-root", str(root)] + [str(a) for a in apps]
    if head:
        args += ["--head-branch", head, "--base-branch", base]
    out = root / "report.json"
    rc = chk.main(args + ["--json", str(out), "--markdown", str(root / "report.md")])
    return rc, json.loads(out.read_text())


def failed_rules(report):
    return {f["rule"] for f in report["errors"]} | {f["rule"] for f in report["warnings"]}


def test_good_caller_app_passes(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root)])
    assert rc == 0 and rep["passed"] and not rep["errors"] and not rep["warnings"]


def test_good_owner_app_passes(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, team="comercial", rights="owner")])
    assert rc == 0, rep


def test_real_sample_apps_pass():
    rc = chk.main(["--repo-root", str(REPO), str(REPO / "apps/finance/sales_by_country"),
                   str(REPO / "apps/comercial/orders_overview")])
    assert rc == 0


@pytest.mark.parametrize("team,name,rule", [
    ("finance", "Bad-Name", "APP001"),
    ("finance", "ab", "APP001"),
    ("marketing", "good_app", "APP002"),
])
def test_path_and_team(tmp_path, team, name, rule):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, team=team, name=name)])
    assert rc == 1 and rule in failed_rules(rep)


def test_missing_app_yml(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, app_yml=False)])
    assert rc == 1 and "APP003" in failed_rules(rep)


def test_invalid_app_yml(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, app_yml="name: [unclosed\n")])
    assert "APP003" in failed_rules(rep)


def test_missing_fields_and_bad_values(tmp_path):
    root = make_repo(tmp_path)
    yml = "name: other_name\ntitle: T\nowner_email: not-an-email\nrights: owner\nviewers: ['bad role!']\n"
    rc, rep = run(root, [make_app(root, app_yml=yml)])
    got = failed_rules(rep)
    # description missing, name mismatch, owner not allowed for FINANCE, bad email, bad viewer
    assert {"APP004", "APP005", "APP006", "APP007", "APP008"} <= got


def test_rights_value_invalid(tmp_path):
    root = make_repo(tmp_path)
    yml = "name: good_app\ntitle: T\ndescription: D\nowner_email: a@b.com\nrights: admin\n"
    rc, rep = run(root, [make_app(root, app_yml=yml)])
    assert "APP006" in failed_rules(rep)


def test_missing_entry_point_and_requirements(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, code=False, req=None)])
    assert {"APP009", "APP010"} <= failed_rules(rep)


@pytest.mark.parametrize("req", ["pandas\n", "pandas>=2.0\n", "streamlit==1.50.0\npandas==2.2.3\n"])
def test_requirements_rules(tmp_path, req):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, req=req)])
    assert rc == 1 and "APP010" in failed_rules(rep)


def test_requirements_extras_and_comments_ok(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, req="# deps\nsnowflake-snowpark-python[pandas]==1.30.0  # pinned\n\n")])
    assert "APP010" not in failed_rules(rep)


def test_get_active_session_and_snowflake_module(tmp_path):
    root = make_repo(tmp_path)
    code = GOOD_CALLER_APP + "from snowflake.snowpark.context import get_active_session\nimport _snowflake\n"
    rc, rep = run(root, [make_app(root, code=code)])
    errs = next(f for f in rep["errors"] if f["rule"] == "APP011")
    assert len(errs["details"]) == 2


def test_use_role_and_warehouse(tmp_path):
    root = make_repo(tmp_path)
    code = GOOD_CALLER_APP + 'callers.query("USE ROLE SYSADMIN")\ncallers.query("use warehouse BIG_WH")\n'
    rc, rep = run(root, [make_app(root, code=code)])
    assert "APP012" in failed_rules(rep)


def test_use_secondary_roles_allowed(tmp_path):
    root = make_repo(tmp_path)
    code = GOOD_CALLER_APP + 'callers.query("USE SECONDARY ROLES ALL")\n'
    rc, rep = run(root, [make_app(root, code=code)])
    assert "APP012" not in failed_rules(rep)


@pytest.mark.parametrize("line", [
    'password = "SuperSecret123"\n',
    'API_KEY="abcd1234efgh"\n',
    'url = "https://myorg-acct.snowflakecomputing.com"\n',
    'k = "-----BEGIN PRIVATE KEY-----"\n',
    'tok = "ghp_abcdefghijklmnopqrstuvwx"\n',
])
def test_secrets_detected(tmp_path, line):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, code=GOOD_CALLER_APP + line)])
    assert rc == 1 and "APP013" in failed_rules(rep)


def test_secret_in_other_file_detected(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, extra={".streamlit/secrets.toml": 'password = "hunter2hunter2"\n'})])
    assert "APP013" in failed_rules(rep)


def test_no_connection(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, team="comercial", rights="owner", code="import streamlit as st\nst.write(1)\n")])
    assert "APP014" in failed_rules(rep)


def test_caller_connection_inside_function(tmp_path):
    root = make_repo(tmp_path)
    code = ('import streamlit as st\n'
            'def get():\n    return st.connection("snowflake-callers-rights")\n'
            'if True:\n    c = st.connection("snowflake-callers-rights")\n')
    rc, rep = run(root, [make_app(root, code=code)])
    f = next(f for f in rep["errors"] if f["rule"] == "APP015")
    assert len(f["details"]) == 2


def test_caller_cache_without_session_scope(tmp_path):
    root = make_repo(tmp_path)
    code = GOOD_CALLER_APP.replace('scope="session"', 'scope="global"') + \
        "@st.cache_data\ndef other():\n    return 1\n"
    rc, rep = run(root, [make_app(root, code=code)])
    f = next(f for f in rep["errors"] if f["rule"] == "APP015")
    assert len(f["details"]) == 2


def test_caller_rights_without_caller_connection(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, code=GOOD_OWNER_APP)])
    assert "APP015" in failed_rules(rep)


def test_owner_rights_using_caller_connection(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, team="comercial", rights="owner", code=GOOD_CALLER_APP)])
    assert "APP015" in failed_rules(rep)


def test_readme_is_warning_only(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, readme=False)])
    assert rc == 0 and [w["rule"] for w in rep["warnings"]] == ["APP016"]


def test_file_too_big(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, extra={"data.csv": b"x" * (1024 * 1024 + 10)})])
    assert "APP017" in failed_rules(rep)


def test_select_star_warning(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, code=GOOD_CALLER_APP.replace("country, amount", "*"))])
    assert rc == 0 and "APP018" in {w["rule"] for w in rep["warnings"]}


@pytest.mark.parametrize("head,base,ok", [
    ("feature/finance-sales-app", "dev", True),
    ("fix/comercial-typo", "dev", True),
    ("feature/marketing-x", "dev", False),
    ("Feature/Finance-X", "dev", False),
    ("my-branch", "dev", False),
    ("feature/platform-cicd-fix", "dev", True),
    ("main", "dev", True),
    ("dev", "main", True),
    ("feature/finance-x", "main", False),
])
def test_branch_rules(tmp_path, head, base, ok):
    root = make_repo(tmp_path)
    rc, rep = run(root, [], head=head, base=base)
    assert (rc == 0) == ok


def test_disabled_rule_is_skipped(tmp_path):
    root = make_repo(tmp_path)
    std = (REPO / "skills/streamlit-app-standards/standards.yml").read_text()
    std = std.replace("  APP016:\n", "  APP016:\n    enabled: false\n")
    (root / "std.yml").write_text(std)
    app = make_app(root, readme=False)
    rc = chk.main(["--repo-root", str(root), "--standards", str(root / "std.yml"), "--json", str(root / "r.json"), str(app)])
    assert rc == 0 and not json.loads((root / "r.json").read_text())["warnings"]


def test_markdown_lists_failures_and_fix(tmp_path):
    root = make_repo(tmp_path)
    run(root, [make_app(root, req="pandas\n")])
    md = (root / "report.md").read_text()
    assert chk.REPORT_MARKER in md and "FAILED" in md and "APP010" in md and "pinned" in md and "blocked" in md


def test_no_apps_passes(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [])
    assert rc == 0 and rep["apps"] == []
