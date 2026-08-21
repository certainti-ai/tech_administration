# Interaction purge — table deletion order

Tables deleted when purging one **interaction**, in execution order (children →
parents; `interactions` anchor last). Pure subtree delete — **no recompute**.
Every table backed up into `data_purge.bak_<table>` before deletion.

## 1. ORG DB — `thinkrd365_org.<account_schema>`

| # | table | scope |
|---|-------|-------|
| 1 | interaction_attachments | interaction_rid |
| 2 | interaction_response_history | interaction_rid **or** via interaction_items |
| 3 | interaction_items | interaction_rid |
| 4 | interaction_timeline | entity_rid |
| 5 | interaction_history | interaction_rid |
| 6 | interaction_status_history | interaction_rid |
| 7 | interaction_send_history | interaction_rid |
| 8 | otp_entries_history | interaction_rid |
| 9 | otp_entries | interaction_rid |
| 10 | **interactions** | rid (anchor — last) |

## 2. MAIN DB — schema `trd365`

| # | table | scope |
|---|-------|-------|
| 11 | send_email_info | interaction_rid |
| 12 | interaction_age_records | interaction_rid |
| 13 | interactions_summary | interaction_rid |

**Deliberately NOT deleted:** `chat_sessions` — carries an `interaction_rid` but
has **no FK** and is a soft reference, not owned by the interaction.

*Order is a fast-path; multi-pass FK deferral corrects any ordering the static
list misses.*
