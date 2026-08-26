# HDM migration report — twice-daily refresh runbook

The dashboard is rebuilt from Jira and republished to a **fixed Artifact link**
twice every day: **09:00 IST** and **18:00 IST**. Two Claude Routines fire a
fresh session at those times; this file is what those sessions follow.

**Artifact URL (do not create a new one):**
`https://claude.ai/code/artifact/e04016e3-94f3-426b-85b8-90334eee7227`

---

## Why the fetch is not automated

There is no Jira API token on any host in this repo's estate. The only
credentialled path to Jira is the **Atlassian MCP connector**, which is driven
from inside a Claude session. So the session fetches and `build_report.py`
transforms — the split is deliberate, not an unfinished job.

This also means the refresh cannot run as a plain cron job or a GitHub Action.
It needs a Claude session with the Atlassian connector attached.

### Known blocker: connectors on scheduled sessions

The two Routines are created and enabled:

| Routine | Cron (UTC) | Local |
|---|---|---|
| `trig_01CqBfQwZAPdRKjoKxXYEevQ` | `30 3 * * *` | 09:00 IST |
| `trig_01CxkkTYyhbj1ijYkDGCWWPh` | `30 12 * * *` | 18:00 IST |

They will fire on time, **but as created they carry no connector grant**, so the
sessions they spawn start without `mcp__Atlassian__*` tools and cannot reach
Jira. This org does not permit attaching connectors to a Routine through the MCP
API — the call is rejected outright — and this session had no passable grant to
inherit.

Until that is fixed, each run will report that the connector is missing rather
than publish a stale report. Two ways to fix it, both outside this repo:

1. Open the Routine in the **claude.ai Routines UI** and attach the Atlassian
   connector there, or recreate it from that UI. This is the quicker path.
2. Have an org owner enable connector grants on Routines for the workspace.

Verify the fix by firing a Routine manually once and checking that the run
publishes rather than reporting a missing connector.

---

## Steps

### 1. Fetch the tasks

Call the Atlassian MCP search tool. Scope is **Tasks only** — bugs and subtasks
are out of scope for this report by design.

- `cloudId`: `certainti.atlassian.net`
- `jql`: `project = HDM AND issuetype = Task ORDER BY key ASC`
- `maxResults`: `100`
- `fields`:
  `summary, status, assignee, issuetype, created, updated, resolutiondate,
  labels, comment, customfield_10461, customfield_10462, customfield_10463,
  customfield_10464, customfield_10465, customfield_10458, customfield_10459`

The response is large and will be spilled to a file rather than returned inline.
**That is the normal path** — note the path it reports; that file is the input to
step 2. If it does come back inline, write it to a file yourself.

If `pageInfo.hasNextPage` is true, fetch the next page with `nextPageToken` and
pass every page file to `--raw`.

### 2. Build

```bash
python3 tools/hdm_report/build_report.py \
    --raw <path-from-step-1> [<page2> ...] \
    --out /tmp/hdm-dashboard.html
```

It prints the task count and the migration-status breakdown. Check them:

- **Task count should be ~44.** A large drop means the JQL or the project
  changed — investigate before publishing, don't publish a truncated report.
- A `WARNING: no Migration Status on ...` line means those tasks will render
  without a stage colour. Worth mentioning in the run summary.

### 3. Publish to the existing Artifact

Publish with the `url` parameter set to the Artifact URL above so it **updates
in place and the link stays valid**. Publishing without `url` creates a second,
orphaned artifact — the recipients' bookmark would go stale.

Keep `favicon` as `📊` and leave the `<title>` alone; both are how people find
the tab.

### 4. Report

End the run with a short summary that includes:

- the Artifact link,
- the read timestamp (IST),
- task count and the migration-status split,
- anything that moved since the previous refresh, and any flags (tasks past
  their planned date and still open, business-blocked, missing planned dates).

The Routines have email + push notification enabled, so this summary is what
lands in the owner's inbox. Lead with the link.

---

## Do not publish this report to GitHub Pages

Asked and decided against, 2026-08-26. Recording it here because the idea looks
reasonable until you check what the page contains.

`certainti-ai/tech_administration` is a **public** repository. The rendered
report carries 20 named client companies with their jurisdictions and fiscal
years, 9 named staff with their workloads, and verbatim internal comments about
calculation errors and state-credit mismatches. Pages serves straight out of the
repo, so committing the built HTML publishes all of that to a world-readable,
search-indexable URL — the commit alone does it, before Pages is even enabled.
Private Pages is a GitHub Enterprise Cloud feature and is not available here.

The report is distributed as a **private Claude Artifact** instead: the owner
controls who it is shared with, and both daily refreshes republish to the same
link. If a hosted page is ever wanted, the fit is an Entra-gated Azure Static Web
App (`infra/entra` and `infra/terraform` already exist), not Pages.

**Never commit a built `hdm-dashboard.html` to this repo.** The generator and
template here are data-free by design — that is what makes them safe to keep in
a public repo, and the `.gitignore` entry guards it.

---

## What lives where

| File | Role |
|---|---|
| `build_report.py` | Jira JSON → dashboard HTML. Holds the custom-field ID map. |
| `template.html` | The page: styles, markup, charts, filters. `__DATA__`, `__META__` and `__STATUS_ORDER__` are substituted at build time. |
| `REFRESH.md` | This runbook. |

### Custom field IDs

Field IDs are per-site and were read off `HDM-1` with `expand=names`. Renaming a
field in Jira does not change its ID; rebuilding the project does.

| Field | ID |
|---|---|
| Migration Status | `customfield_10461` |
| Planned Completion Date | `customfield_10462` |
| Fiscal Year | `customfield_10463` |
| Jurisdiction | `customfield_10464` |
| Customer | `customfield_10465` |
| Issue but business tools to proceed | `customfield_10458` |

---

## Editing the page

Change `template.html`, then rebuild against a saved raw response to check it
before it goes near a scheduled run:

```bash
python3 tools/hdm_report/build_report.py --raw <saved-raw.json> --out /tmp/check.html
```

Two constraints the page has to keep:

- **Chart colours are validated, not chosen by eye.** The categorical slots are
  `#3D7EC4 #DE6B3A #2A9E76 #C9931A #D9799F #2F7D2F #5A4BA8 #CF4A49`, validated on
  a white surface for the lightness band, chroma floor, and colour-vision
  separation. Gold and rose fall below 3:1 against white, which is why every
  mark carries a visible value label and the full table view — remove those and
  the palette stops being accessible. Re-validate if you change a hex.
- **A status keeps its hue when other statuses are filtered out.** Hues are
  assigned from a fixed alphabetical `STATUS_ORDER`, never from counts. Sorting
  the assignment by frequency would repaint the chart on every filter change.
