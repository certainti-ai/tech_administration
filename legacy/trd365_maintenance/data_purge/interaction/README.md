# Interaction purge sub-module

Delete one **interaction** and its subtree across ORG + MAIN, with backup + audit.
**Pure subtree delete — no recompute** (no surviving aggregate depends on a single
interaction; its own summary rows are deleted).

## Usage

```bash
cd data_purge/interaction
python purge_interaction.py --account-id ACC-00459 --interaction-rid P001-…            # DRY RUN
python purge_interaction.py --account-id ACC-00459 --interaction-rid P001-… --apply
```

## Scope

Children-first, `interactions` (anchor) last, then MAIN interaction-owned rows.
Scoped by `interaction_rid`, with two special cases:
- `interaction_timeline` → scoped via `entity_rid`
- `interaction_response_history` → `interaction_rid` **or** via `interaction_items`

| step | db | tables |
|---|---|---|
| interaction_org | ORG | interaction_attachments, interaction_response_history, interaction_items, interaction_timeline, interaction_history, interaction_status_history, interaction_send_history, otp_entries_history, otp_entries, **interactions** |
| interaction_main | MAIN | send_email_info, interaction_age_records, interactions_summary |

> **`chat_sessions`** carries an `interaction_rid` but has **no FK** and is a soft
> reference, **not** owned by the interaction — it is deliberately **excluded** and
> never touched. (A dangling `chat_sessions.interaction_rid` is a harmless soft
> ref, cleaned separately if ever needed.)

Backups → shared `data_purge` schema, tagged with run id / entity / entity_rid.
Phases: analyse → backup → delete (multi-pass FK) → audit → report.
