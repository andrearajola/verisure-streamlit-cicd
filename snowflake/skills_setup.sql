-- =====================================================================
-- Skill CI/CD (DEV) - objects + procedures. Run by the pipeline role before every sync (idempotent):
--   snow sql -x -f snowflake/skills_setup.sql -D db=DB_STREAMLIT
-- dev branch -> <db>.SKILLS_DEV.<SKILL>  ("[DEV]" description, READ to <SKILL>_SKILL_DEV, release email)
-- Source: GitHub Actions uploads skills/ to @<db>.SKILLS_CICD.SKILL_SRC/dev/skills/<skill>/ and calls
-- SP_SKILL_SYNC_ALL('dev', '<commit>', '<email,email>'). Only skills whose files changed get a new version.
-- The reader role <SKILL>_SKILL_DEV is created by the admin (snowflake/00_admin_setup.sql).
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS <% db %>.SKILLS_CICD COMMENT = 'Skill CI/CD: stage, state and procedures';
CREATE SCHEMA IF NOT EXISTS <% db %>.SKILLS_DEV  COMMENT = 'Skills published from the dev branch';

-- Server-side encryption: the md5 of a file is stable, so it can be used to detect changes
CREATE STAGE IF NOT EXISTS <% db %>.SKILLS_CICD.SKILL_SRC ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');
CREATE STAGE IF NOT EXISTS <% db %>.SKILLS_CICD.SEED;

CREATE TABLE IF NOT EXISTS <% db %>.SKILLS_CICD.SKILL_DEPLOY_STATE (
  RUN_TS      TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
  SKILL       STRING,
  BRANCH      STRING,
  EXTENSION   STRING,
  COMMIT_HASH STRING,
  ALIAS       STRING,
  STATUS      STRING,      -- DEPLOYED / FAILED
  MESSAGE     STRING,
  FINGERPRINT STRING
);

CREATE FILE FORMAT IF NOT EXISTS <% db %>.SKILLS_CICD.FF_SKILL_TEXT
  TYPE = CSV FIELD_DELIMITER = NONE RECORD_DELIMITER = '\n'
  ESCAPE_UNENCLOSED_FIELD = NONE FIELD_OPTIONALLY_ENCLOSED_BY = NONE;

-- Release email to a fixed list of addresses (must be in the integration's ALLOWED_RECIPIENTS)
CREATE OR REPLACE PROCEDURE <% db %>.SKILLS_CICD.SP_SKILL_NOTIFY(
  P_EXT STRING, P_SKILL STRING, P_DESC STRING, P_COMMIT STRING, P_TO STRING)
RETURNS STRING
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  v_sent   INTEGER DEFAULT 0;
  v_failed INTEGER DEFAULT 0;
  v_skill  STRING;
  v_desc   STRING;
  v_subj   STRING;
  v_html   STRING;
  v_to     STRING;
  rs       RESULTSET;
BEGIN
  v_skill := REPLACE(REPLACE(REPLACE(P_SKILL, '&', '&amp;'), '<', '&lt;'), '>', '&gt;');
  v_desc  := REPLACE(REPLACE(REPLACE(COALESCE(P_DESC, '-'), '&', '&amp;'), '<', '&lt;'), '>', '&gt;');
  v_subj  := 'Skill ' || P_SKILL || ' - new DEV version available';
  v_html  := '<h3>New version of the skill <code>' || v_skill || '</code> (DEV)</h3>' ||
             '<p><b>Description:</b> ' || v_desc || '</p>' ||
             '<p><b>Commit:</b> ' || P_COMMIT || '</p>' ||
             '<p><b>How to use it:</b> in CoCo (Snowsight or Desktop) type <code>/' || v_skill || '</code>.</p>' ||
             '<p><b>Snowsight:</b> nothing to do, it already uses the new version.</p>' ||
             '<p><b>CoCo Desktop / CLI:</b><br><code>cortex skill update snow://skill_catalog/' || P_EXT || '</code></p>';
  rs := (SELECT TRIM(VALUE::STRING) AS ADDR FROM TABLE(FLATTEN(INPUT => SPLIT(:P_TO, ',')))
         WHERE REGEXP_LIKE(TRIM(VALUE::STRING), '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$'));
  FOR r IN rs DO
    v_to := r.ADDR;
    BEGIN
      CALL SYSTEM$SEND_SNOWFLAKE_NOTIFICATION(
        SNOWFLAKE.NOTIFICATION.TEXT_HTML(:v_html),
        SNOWFLAKE.NOTIFICATION.EMAIL_INTEGRATION_CONFIG('SKILLS_EMAIL_INT', :v_subj, ARRAY_CONSTRUCT(:v_to)));
      v_sent := v_sent + 1;
    EXCEPTION
      WHEN OTHER THEN v_failed := v_failed + 1;
    END;
  END FOR;
  RETURN 'Emails sent: ' || v_sent || ', failed: ' || v_failed;
END;
$$;

CREATE OR REPLACE PROCEDURE <% db %>.SKILLS_CICD.SP_SKILL_SYNC(P_SKILL STRING, P_BRANCH STRING, P_COMMIT STRING, P_TO STRING)
RETURNS STRING
LANGUAGE SQL
EXECUTE AS CALLER   -- LIST is not allowed in owner's rights; the workflow runs as the pipeline role
AS
$$
DECLARE
  v_name    STRING;
  v_schema  STRING;
  v_reader  STRING;
  v_ext     STRING;
  v_last    STRING;
  v_alias   STRING;
  v_src     STRING;
  v_sql     STRING;
  v_ok      INTEGER;
  v_desc    STRING;
  v_exists  INTEGER;
  v_open    BOOLEAN DEFAULT FALSE;
  v_status  STRING;
  v_msg     STRING;
  v_fp      STRING;
  v_nfiles  INTEGER;
  v_nrole   INTEGER;
  v_mail    STRING;
BEGIN
  -- Inputs end up in identifiers and paths: validate them
  IF (NOT REGEXP_LIKE(P_SKILL, '^[a-z0-9]+(-[a-z0-9]+)*$')) THEN
    RETURN 'Invalid skill name: ' || P_SKILL;
  END IF;
  IF (NOT REGEXP_LIKE(P_COMMIT, '^[0-9a-f]{7,40}$')) THEN
    RETURN 'Invalid commit: ' || P_COMMIT;
  END IF;
  IF (P_BRANCH <> 'dev') THEN
    RETURN 'Branch not deployed: ' || P_BRANCH;
  END IF;

  v_schema := '<% db %>.SKILLS_DEV';
  v_name   := UPPER(REPLACE(P_SKILL, '-', '_'));
  v_reader := REGEXP_REPLACE(v_name, '_SKILL$', '') || '_SKILL_DEV';
  v_ext    := v_schema || '.' || v_name;
  v_src    := '@<% db %>.SKILLS_CICD.SKILL_SRC/' || P_BRANCH || '/skills/' || P_SKILL || '/';

  BEGIN
    -- Fingerprint of this skill's folder only
    v_sql := 'LIST ' || v_src;
    EXECUTE IMMEDIATE :v_sql;
    SELECT COUNT(*), MD5(LISTAGG(REGEXP_SUBSTR("name", 'skills/.*$') || ':' || "md5", ',') WITHIN GROUP (ORDER BY "name"))
      INTO :v_nfiles, :v_fp
      FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
    SELECT MAX_BY(FINGERPRINT, RUN_TS) INTO :v_last
      FROM <% db %>.SKILLS_CICD.SKILL_DEPLOY_STATE
      WHERE SKILL = :P_SKILL AND BRANCH = :P_BRANCH AND STATUS = 'DEPLOYED';

    IF (v_nfiles = 0) THEN
      v_status := 'SKIP'; v_msg := 'skill not on this branch';
    ELSEIF (v_last = v_fp) THEN
      v_status := 'SKIP'; v_msg := 'unchanged since last run';
    ELSE
      v_sql := 'SHOW ROLES LIKE ''' || v_reader || '''';
      EXECUTE IMMEDIATE :v_sql;
      SELECT COUNT(*) INTO :v_nrole FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
      v_alias := 'G' || UPPER(LEFT(P_COMMIT, 7));

      -- SKILL.md exists and its front-matter has name + description
      v_sql := 'SELECT COUNT_IF(STARTSWITH(TRIM($1), ''name:'')) * COUNT_IF(STARTSWITH(TRIM($1), ''description:'')), ' ||
               'MIN(IFF(STARTSWITH(TRIM($1), ''description:''), TRIM(SUBSTR(TRIM($1), 13), '' "''''''), NULL)) ' ||
               'FROM ' || v_src || 'SKILL.md (FILE_FORMAT => ''<% db %>.SKILLS_CICD.FF_SKILL_TEXT'')';
      EXECUTE IMMEDIATE :v_sql;
      SELECT $1, LEFT(REPLACE($2, '''', ''''''), 1000) INTO :v_ok, :v_desc FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
      IF (COALESCE(v_desc, '') = '') THEN v_ok := 0; ELSE v_desc := LEFT('[DEV] ' || v_desc, 1024); END IF;

      IF (v_nrole = 0) THEN
        v_status := 'FAILED'; v_msg := 'reader role ' || v_reader || ' not found: ask the admin to create it';
      ELSEIF (COALESCE(v_ok, 0) = 0) THEN
        v_status := 'FAILED'; v_msg := 'SKILL.md missing name or description';
      ELSE
        v_sql := 'SHOW CORTEX EXTENSIONS LIKE ''' || v_name || ''' IN SCHEMA ' || v_schema;
        EXECUTE IMMEDIATE :v_sql;
        SELECT COUNT(*) INTO :v_exists FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));

        IF (v_exists = 0) THEN
          -- Day 1: create the extension (root must contain only skills/<skill>/ -> SEED stage)
          v_sql := 'COPY FILES INTO @<% db %>.SKILLS_CICD.SEED/' || v_alias || '/skills/' || P_SKILL || '/ FROM ' || v_src;
          EXECUTE IMMEDIATE :v_sql;
          v_sql := 'CREATE CORTEX EXTENSION ' || v_ext || ' FROM ''@<% db %>.SKILLS_CICD.SEED/' || v_alias || '/''';
          EXECUTE IMMEDIATE :v_sql;
          v_sql := 'ALTER CORTEX EXTENSION ' || v_ext || ' SET COMMENT = ''' || v_desc || '''';
          EXECUTE IMMEDIATE :v_sql;
          -- Pilot: discoverable so it shows in the CoCo catalog (only roles with READ can use it)
          v_sql := 'ALTER CORTEX EXTENSION ' || v_ext || ' SET DISCOVERABLE = TRUE';
          EXECUTE IMMEDIATE :v_sql;
          v_status := 'DEPLOYED'; v_msg := 'created';
        ELSE
          v_sql := 'SHOW VERSIONS IN CORTEX EXTENSION ' || v_ext;
          EXECUTE IMMEDIATE :v_sql;
          SELECT COUNT(*) INTO :v_exists FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())) WHERE "alias" = :v_alias;
          IF (v_exists > 0) THEN
            v_status := 'DEPLOYED'; v_msg := 'already present';
          ELSE
            v_sql := 'ALTER CORTEX EXTENSION ' || v_ext || ' ADD LIVE VERSION ' || v_alias || ' FROM LAST';
            EXECUTE IMMEDIATE :v_sql;
            v_open := TRUE;
            -- Replace the files: a file deleted in git disappears from the skill
            v_sql := 'REMOVE ''snow://cortex_extension/' || v_ext || '/versions/live/skills/' || P_SKILL || '/''';
            EXECUTE IMMEDIATE :v_sql;
            v_sql := 'COPY FILES INTO ''snow://cortex_extension/' || v_ext || '/versions/live/skills/' || P_SKILL || '/'' FROM ''' || v_src || '''';
            EXECUTE IMMEDIATE :v_sql;
            v_sql := 'ALTER CORTEX EXTENSION ' || v_ext || ' COMMIT DESCRIPTION = ''' || v_desc || '''';
            EXECUTE IMMEDIATE :v_sql;
            v_open := FALSE;
            v_sql := 'ALTER CORTEX EXTENSION ' || v_ext || ' SET COMMENT = ''' || v_desc || '''';
            EXECUTE IMMEDIATE :v_sql;
            v_status := 'DEPLOYED'; v_msg := 'new version';
          END IF;
        END IF;
        -- Reader grant every time (idempotent): also repairs a grant removed by hand
        v_sql := 'GRANT READ ON CORTEX EXTENSION ' || v_ext || ' TO ROLE ' || v_reader;
        EXECUTE IMMEDIATE :v_sql;

        IF (v_msg IN ('created', 'new version') AND COALESCE(P_TO, '') <> '') THEN
          v_desc := REPLACE(v_desc, '''''', '''');
          CALL <% db %>.SKILLS_CICD.SP_SKILL_NOTIFY(:v_ext, :P_SKILL, :v_desc, :P_COMMIT, :P_TO) INTO :v_mail;
          v_msg := v_msg || ', READ to ' || v_reader || ', notified (' || v_mail || ')';
        END IF;
      END IF;
    END IF;

  EXCEPTION
    WHEN OTHER THEN
      v_status := 'FAILED'; v_msg := SQLERRM;
      IF (v_open) THEN
        v_sql := 'ALTER CORTEX EXTENSION ' || v_ext || ' ABORT';
        EXECUTE IMMEDIATE :v_sql;
      END IF;
  END;

  IF (v_status <> 'SKIP') THEN
    INSERT INTO <% db %>.SKILLS_CICD.SKILL_DEPLOY_STATE (SKILL, BRANCH, EXTENSION, COMMIT_HASH, ALIAS, STATUS, MESSAGE, FINGERPRINT)
      VALUES (:P_SKILL, :P_BRANCH, :v_ext, :P_COMMIT, :v_alias, :v_status, :v_msg, :v_fp);
  END IF;
  RETURN P_BRANCH || ': ' || COALESCE(v_alias || ' ', '') || v_status || ' (' || v_msg || ')';
END;
$$;

-- All skills uploaded for one branch
CREATE OR REPLACE PROCEDURE <% db %>.SKILLS_CICD.SP_SKILL_SYNC_ALL(P_BRANCH STRING, P_COMMIT STRING, P_TO STRING)
RETURNS STRING
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
  v_r    STRING;
  v_s    STRING;
  v_sql  STRING;
  v_out  STRING DEFAULT '';
  skills RESULTSET;
BEGIN
  IF (P_BRANCH <> 'dev') THEN
    RETURN 'Branch not deployed: ' || P_BRANCH;
  END IF;
  v_sql := 'LIST @<% db %>.SKILLS_CICD.SKILL_SRC/' || P_BRANCH || '/skills/ PATTERN = ''.*/[a-z0-9-]+/SKILL[.]md''';
  EXECUTE IMMEDIATE :v_sql;
  skills := (SELECT DISTINCT REGEXP_SUBSTR("name", 'skills/([a-z0-9-]+)/SKILL[.]md$', 1, 1, 'e', 1) AS SKILL
             FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())) WHERE SKILL IS NOT NULL ORDER BY 1);
  FOR s IN skills DO
    v_r := NULL; v_s := s.SKILL;
    CALL <% db %>.SKILLS_CICD.SP_SKILL_SYNC(:v_s, :P_BRANCH, :P_COMMIT, :P_TO) INTO :v_r;
    v_out := v_out || v_s || ' => ' || COALESCE(v_r, 'no result') || CHR(10);
  END FOR;
  RETURN COALESCE(NULLIF(v_out, ''), 'no skills found for ' || P_BRANCH);
END;
$$;
