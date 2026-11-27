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


TEST_ENVS = """\
dev:
  database: TEST_DB
  compute_pool: TEST_POOL
"""


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "teams.yml").write_text(TEST_TEAMS)
    (tmp_path / "config" / "envs.yml").write_text(TEST_ENVS)
    return tmp_path


def snowflake_yml(name="good_app", schema="FINANCE", warehouse="FINANCE_WH", extra=""):
    return textwrap.dedent(f"""\
        definition_version: 2
        entities:
          dev:
            type: streamlit
            identifier:
              name: {name.upper()}
              database: TEST_DB
              schema: {schema}
            main_file: streamlit_app.py
            query_warehouse: {warehouse}
            compute_pool: TEST_POOL
            runtime_name: SYSTEM$ST_CONTAINER_RUNTIME_PY3_11
        """) + extra


def pyproject(deps=None, name="good-app"):
    lines = ", ".join(f'"{x}"' for x in (deps or []))
    return f'[project]\nname = "{name}"\nversion = "0.1.0"\nrequires-python = ">=3.11"\ndependencies = [{lines}]\n'


def make_app(root: Path, team="finance", name="good_app", rights="caller", code=None,
             deps=("pandas==2.2.3",), app_yml=None, readme=True, extra=None, sf_yml=None,
             config=True) -> Path:
    """deps=None: no pyproject.toml. sf_yml=None: a snowflake.yml that matches; False: none."""
    d = root / "apps" / team / name
    d.mkdir(parents=True)
    if code is not False:
        (d / "streamlit_app.py").write_text(code if code is not None else
                                            (GOOD_CALLER_APP if rights == "caller" else GOOD_OWNER_APP))
    if deps is not None:
        (d / "pyproject.toml").write_text(pyproject(list(deps)))
    if sf_yml is not False:
        schema = "COMERCIAL" if team == "comercial" else "FINANCE"
        (d / "snowflake.yml").write_text(sf_yml if sf_yml is not None else
                                         snowflake_yml(name, schema, f"{schema}_WH"))
    if config:
        (d / ".streamlit").mkdir()
        (d / ".streamlit" / "config.toml").write_text("[server]\nrunOnSave = true\n")
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


def run(root: Path, apps=(), head="", base="", allow_packages=True):
    # Rule tests use a copy of the real standards; allow_packages switches APP010 between
    # "exact pins allowed" and "no PyPI access: pyproject.toml dependencies must be empty"
    std = chk.yaml.safe_load(chk.DEFAULT_STANDARDS.read_text(encoding="utf-8"))
    std["rules"]["APP010"]["allow_packages"] = allow_packages
    std_file = root / "standards.json"
    std_file.write_text(json.dumps(std))
    args = ["--repo-root", str(root), "--standards", str(std_file)] + [str(a) for a in apps]
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
    yml = "name: other_name\ntitle: T\nowner_email: not-an-email\nrights: owner\n"
    rc, rep = run(root, [make_app(root, app_yml=yml)])
    got = failed_rules(rep)
    # description missing, name mismatch, owner not allowed for FINANCE, bad email
    assert {"APP004", "APP005", "APP006", "APP007"} <= got


def test_rights_value_invalid(tmp_path):
    root = make_repo(tmp_path)
    yml = "name: good_app\ntitle: T\ndescription: D\nowner_email: a@b.com\nrights: admin\n"
    rc, rep = run(root, [make_app(root, app_yml=yml)])
    assert "APP006" in failed_rules(rep)


def test_missing_entry_point_and_pyproject(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, code=False, deps=None)])
    assert {"APP009", "APP010"} <= failed_rules(rep)


@pytest.mark.parametrize("deps", [["pandas"], ["pandas>=2.0"], ["streamlit==1.50.0", "pandas==2.2.3"]])
def test_dependency_rules(tmp_path, deps):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, deps=deps)])
    assert rc == 1 and "APP010" in failed_rules(rep)


def test_dependency_extras_ok(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, deps=["snowflake-snowpark-python[pandas]==1.30.0"])])
    assert "APP010" not in failed_rules(rep)


def test_requirements_txt_not_allowed(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, extra={"requirements.txt": ""})])
    assert rc == 1 and "APP010" in failed_rules(rep)


@pytest.mark.parametrize("content", ["[project\n", "[tool.x]\na = 1\n", "[project]\ndependencies = []\n"])
def test_pyproject_invalid_or_incomplete(tmp_path, content):
    root = make_repo(tmp_path)
    app = make_app(root)
    (app / "pyproject.toml").write_text(content)
    rc, rep = run(root, [app])
    assert rc == 1 and "APP010" in failed_rules(rep)


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
    app = make_app(root, readme=False, deps=())
    rc = chk.main(["--repo-root", str(root), "--standards", str(root / "std.yml"), "--json", str(root / "r.json"), str(app)])
    assert rc == 0 and not json.loads((root / "r.json").read_text())["warnings"]


def test_markdown_lists_failures_and_fix(tmp_path):
    root = make_repo(tmp_path)
    run(root, [make_app(root, deps=["pandas"])])
    md = (root / "report.md").read_text()
    assert chk.REPORT_MARKER in md and "FAILED" in md and "APP010" in md and "pinned" in md and "blocked" in md


def test_no_apps_passes(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [])
    assert rc == 0 and rep["apps"] == []


def test_no_pypi_empty_dependencies_pass(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, deps=())], allow_packages=False)
    assert rc == 0, rep


@pytest.mark.parametrize("deps", [["pandas==2.2.3"], ["altair"]])
def test_no_pypi_any_package_fails(tmp_path, deps):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, deps=deps)], allow_packages=False)
    assert rc == 1 and "APP010" in failed_rules(rep)


def test_repo_standards_forbid_packages():
    # The pilot has no PyPI integration: the real standards must keep APP010 strict
    std = chk.yaml.safe_load(chk.DEFAULT_STANDARDS.read_text(encoding="utf-8"))
    assert std["rules"]["APP010"]["allow_packages"] is False


# -- APP019 snowflake.yml / APP020 .streamlit/config.toml ---------------------

def test_snowflake_yml_missing(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, sf_yml=False)])
    assert rc == 1 and "APP019" in failed_rules(rep)


@pytest.mark.parametrize("old, new", [
    ("name: GOOD_APP", "name: OTHER_APP"),
    ("database: TEST_DB", "database: OTHER_DB"),
    ("schema: FINANCE", "schema: COMERCIAL"),
    ("main_file: streamlit_app.py", "main_file: app.py"),
    ("query_warehouse: FINANCE_WH", "query_warehouse: BIG_WH"),
    ("compute_pool: TEST_POOL", "compute_pool: OTHER_POOL"),
    ("SYSTEM$ST_CONTAINER_RUNTIME_PY3_11", "SYSTEM$WAREHOUSE_RUNTIME"),
    ("definition_version: 2", "definition_version: 1"),
    ("  dev:", "  prd:"),
])
def test_snowflake_yml_mismatch(tmp_path, old, new):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, sf_yml=snowflake_yml().replace(old, new))])
    assert rc == 1 and "APP019" in failed_rules(rep), rep


def test_snowflake_yml_grants_not_allowed(tmp_path):
    root = make_repo(tmp_path)
    yml = snowflake_yml(extra="    grants:\n      - privilege: USAGE\n        role: ANALYST\n")
    rc, rep = run(root, [make_app(root, sf_yml=yml)])
    assert rc == 1 and "APP019" in failed_rules(rep)


def test_snowflake_yml_with_mixins_passes(tmp_path):
    # The shape Snowsight writes after Settings: shared values in a mixin
    yml = textwrap.dedent("""\
        definition_version: 2
        mixins:
          streamlit_shared:
            main_file: streamlit_app.py
            query_warehouse: finance_wh
            compute_pool: TEST_POOL
            runtime_name: SYSTEM$ST_CONTAINER_RUNTIME_PY3_11
        entities:
          dev:
            type: streamlit
            identifier: {name: good_app, database: test_db, schema: finance}
            meta:
              use_mixins: [streamlit_shared]
        """)
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, sf_yml=yml)])
    assert "APP019" not in failed_rules(rep), rep


def test_snowflake_yml_invalid_yaml(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, sf_yml="entities: [unclosed\n")])
    assert rc == 1 and "APP019" in failed_rules(rep)


def test_streamlit_config_missing_is_warning(tmp_path):
    root = make_repo(tmp_path)
    rc, rep = run(root, [make_app(root, config=False)])
    assert rc == 0 and "APP020" in {f["rule"] for f in rep["warnings"]}


def test_repo_apps_pass(tmp_path):
    # The apps in the repo are real Snowsight projects and must pass with the real config
    apps = sorted(str(p) for p in (REPO / "apps").glob("*/*") if p.is_dir())
    assert apps and chk.main(["--repo-root", str(REPO), "--json", str(tmp_path / "r.json")] + apps) == 0
