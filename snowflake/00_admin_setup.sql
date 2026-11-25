-- One-time admin setup for the Streamlit CI/CD pilot in the Verisure DEV account.
-- Run by a Verisure admin (ACCOUNTADMIN, or a role with CREATE ROLE, CREATE USER and CREATE NETWORK POLICY).
-- Everything else (schemas, stages, apps, test data) is created by the pipeline role itself.
USE ROLE ACCOUNTADMIN;

-- 1. Pipeline role, limited to the new database
CREATE ROLE IF NOT EXISTS STREAMLIT_CICD_DEV COMMENT = 'CI/CD Streamlit (GitHub Actions) - pilot';
GRANT OWNERSHIP ON DATABASE DB_STREAMLIT TO ROLE STREAMLIT_CICD_DEV COPY CURRENT GRANTS;
GRANT USAGE ON WAREHOUSE VWH_STREAMLIT TO ROLE STREAMLIT_CICD_DEV;
GRANT USAGE ON COMPUTE POOL SYSTEM_COMPUTE_POOL_CPU TO ROLE STREAMLIT_CICD_DEV;
GRANT ROLE STREAMLIT_CICD_DEV TO USER "<CONSULTANT_USER>";   -- to see what was deployed

-- 2. Service user with Workload Identity Federation (GitHub OIDC): no password, no key.
--    Only accepts tokens from this repo, GitHub environment "dev".
CREATE USER IF NOT EXISTS SVC_STREAMLIT_CICD_DEV
  TYPE = SERVICE
  DEFAULT_ROLE = STREAMLIT_CICD_DEV
  DEFAULT_WAREHOUSE = VWH_STREAMLIT
  WORKLOAD_IDENTITY = (
    TYPE = OIDC
    ISSUER = 'https://token.actions.githubusercontent.com'
    SUBJECT = 'repo:andrearajola@102627835/verisure-streamlit-cicd@1471706956:environment:dev')
  COMMENT = 'GitHub Actions - CI/CD Streamlit (pilot)';
GRANT ROLE STREAMLIT_CICD_DEV TO USER SVC_STREAMLIT_CICD_DEV;

-- 3. Network: only GitHub Actions runners can use this user (Snowflake-managed rule, kept up to date).
CREATE NETWORK POLICY IF NOT EXISTS NP_GITHUB_ACTIONS
  ALLOWED_NETWORK_RULE_LIST = ('SNOWFLAKE.NETWORK_SECURITY.GITHUBACTIONS_GLOBAL')
  COMMENT = 'GitHub Actions runners -> CI/CD service user';
ALTER USER SVC_STREAMLIT_CICD_DEV SET NETWORK_POLICY = NP_GITHUB_ACTIONS;

-- 4. Check
DESC USER SVC_STREAMLIT_CICD_DEV;

-- Moving the repo to the Verisure GitHub organization later: only the subject changes.
-- ALTER USER SVC_STREAMLIT_CICD_DEV SET WORKLOAD_IDENTITY = (TYPE = OIDC
--   ISSUER = 'https://token.actions.githubusercontent.com'
--   SUBJECT = 'repo:<org>@<org_id>/<repo>@<repo_id>:environment:dev');
