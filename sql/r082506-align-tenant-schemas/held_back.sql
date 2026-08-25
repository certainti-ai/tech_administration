-- Held back — changes that NARROW a column
--
-- Every statement here would align the column to trd365_00440 and could lose
-- data doing it. None is included in 02_align.  Measure first: each block runs
-- a read-only query that says whether the narrowing is safe *today*, and the
-- ALTER underneath it is commented out.
--
-- A zero result means no current row would be harmed. It does not mean the
-- application will not write a wider value tomorrow — that is a code question,
-- not a data one.
\set ON_ERROR_STOP on


-- trd365_00353.case_technical_summary.eid:  varchar(120)  ->  varchar(50)
SELECT count(*) AS would_be_truncated FROM "trd365_00353"."case_technical_summary" WHERE length("eid") > 50;
-- ALTER TABLE "trd365_00353"."case_technical_summary" ALTER COLUMN "eid" TYPE varchar(50) USING "eid"::varchar(50);

-- trd365_00353.project_fiscal.total_nonlabor_from_prj_res:  numeric(18,2)  ->  integer
SELECT count(*) AS would_lose_decimals FROM "trd365_00353"."project_fiscal" WHERE "total_nonlabor_from_prj_res" <> trunc("total_nonlabor_from_prj_res");
-- ALTER TABLE "trd365_00353"."project_fiscal" ALTER COLUMN "total_nonlabor_from_prj_res" TYPE integer USING "total_nonlabor_from_prj_res"::integer;

-- trd365_00353.webhook_email_history.created_datetime:  timestamp with time zone  ->  timestamp without time zone
-- Dropping the time zone rewrites every value to the session zone.
SELECT count(*) AS rows_affected FROM "trd365_00353"."webhook_email_history" WHERE "created_datetime" IS NOT NULL;
-- ALTER TABLE "trd365_00353"."webhook_email_history" ALTER COLUMN "created_datetime" TYPE timestamp without time zone USING "created_datetime"::timestamp without time zone;

-- trd365_00353.webhook_email_history.uploaded_time:  timestamp with time zone  ->  timestamp without time zone
-- Dropping the time zone rewrites every value to the session zone.
SELECT count(*) AS rows_affected FROM "trd365_00353"."webhook_email_history" WHERE "uploaded_time" IS NOT NULL;
-- ALTER TABLE "trd365_00353"."webhook_email_history" ALTER COLUMN "uploaded_time" TYPE timestamp without time zone USING "uploaded_time"::timestamp without time zone;

-- trd365_00363.case_technical_summary.eid:  varchar(120)  ->  varchar(50)
SELECT count(*) AS would_be_truncated FROM "trd365_00363"."case_technical_summary" WHERE length("eid") > 50;
-- ALTER TABLE "trd365_00363"."case_technical_summary" ALTER COLUMN "eid" TYPE varchar(50) USING "eid"::varchar(50);

-- trd365_00363.project_fiscal.total_nonlabor_from_prj_res:  numeric(18,2)  ->  integer
SELECT count(*) AS would_lose_decimals FROM "trd365_00363"."project_fiscal" WHERE "total_nonlabor_from_prj_res" <> trunc("total_nonlabor_from_prj_res");
-- ALTER TABLE "trd365_00363"."project_fiscal" ALTER COLUMN "total_nonlabor_from_prj_res" TYPE integer USING "total_nonlabor_from_prj_res"::integer;

-- trd365_00363.webhook_email_history.created_datetime:  timestamp with time zone  ->  timestamp without time zone
-- Dropping the time zone rewrites every value to the session zone.
SELECT count(*) AS rows_affected FROM "trd365_00363"."webhook_email_history" WHERE "created_datetime" IS NOT NULL;
-- ALTER TABLE "trd365_00363"."webhook_email_history" ALTER COLUMN "created_datetime" TYPE timestamp without time zone USING "created_datetime"::timestamp without time zone;

-- trd365_00363.webhook_email_history.uploaded_time:  timestamp with time zone  ->  timestamp without time zone
-- Dropping the time zone rewrites every value to the session zone.
SELECT count(*) AS rows_affected FROM "trd365_00363"."webhook_email_history" WHERE "uploaded_time" IS NOT NULL;
-- ALTER TABLE "trd365_00363"."webhook_email_history" ALTER COLUMN "uploaded_time" TYPE timestamp without time zone USING "uploaded_time"::timestamp without time zone;

-- trd365_00385.case_technical_summary.eid:  varchar(120)  ->  varchar(50)
SELECT count(*) AS would_be_truncated FROM "trd365_00385"."case_technical_summary" WHERE length("eid") > 50;
-- ALTER TABLE "trd365_00385"."case_technical_summary" ALTER COLUMN "eid" TYPE varchar(50) USING "eid"::varchar(50);

-- trd365_00386.case_technical_summary.eid:  varchar(120)  ->  varchar(50)
SELECT count(*) AS would_be_truncated FROM "trd365_00386"."case_technical_summary" WHERE length("eid") > 50;
-- ALTER TABLE "trd365_00386"."case_technical_summary" ALTER COLUMN "eid" TYPE varchar(50) USING "eid"::varchar(50);

-- trd365_00388.case_technical_summary.eid:  varchar(120)  ->  varchar(50)
SELECT count(*) AS would_be_truncated FROM "trd365_00388"."case_technical_summary" WHERE length("eid") > 50;
-- ALTER TABLE "trd365_00388"."case_technical_summary" ALTER COLUMN "eid" TYPE varchar(50) USING "eid"::varchar(50);

-- trd365_00393.case_technical_summary.eid:  varchar(120)  ->  varchar(50)
SELECT count(*) AS would_be_truncated FROM "trd365_00393"."case_technical_summary" WHERE length("eid") > 50;
-- ALTER TABLE "trd365_00393"."case_technical_summary" ALTER COLUMN "eid" TYPE varchar(50) USING "eid"::varchar(50);
