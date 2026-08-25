# Not aligned — tenant identity defaults

241 column defaults differ between schemas and are
deliberately left alone. They encode *which tenant* the row belongs to:

| Column | Schemas |
|---|---|
| `checklists.r_number` | 23 |
| `chat_answers.answer_rid` | 20 |
| `chat_attachments.attachment_rid` | 20 |
| `chat_audit_log.audit_rid` | 20 |
| `chat_branches.branch_rid` | 20 |
| `chat_messages.message_rid` | 20 |
| `chat_questions.question_rid` | 20 |
| `chat_session_config.config_rid` | 20 |
| `chat_sessions.session_rid` | 20 |
| `case_technical_summary.r_number` | 19 |
| `project_timeline.rid` | 11 |
| `account_fiscal.r_number` | 10 |
| `account_fiscal_region.r_number` | 10 |
| `project_resource_timeline.r_number` | 8 |

Three shapes, all of them fatal to copy between schemas:

- `nextval('trd365_00440.foo_seq')` — the sequence is named by schema, so
  aligning would point this tenant's ids at another tenant's counter.
- `('P001-' || gen_random_uuid())` — the literal prefix *is* the tenant code.
- `('${ENV_PREFIX}' || gen_random_uuid())` — an unsubstituted template.

The last one is not drift: `project_timeline.rid` carries it in **24 of 26**
schemas, so every row inserted there without an explicit rid gets a literal
`${ENV_PREFIX}-<uuid>`. That is a provisioning defect to fix everywhere, not
a difference to align.
