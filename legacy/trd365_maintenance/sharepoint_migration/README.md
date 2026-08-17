# Cross-tenant SharePoint site migration

Copies one SharePoint site's **document libraries + folders + files** from a
**source tenant** to a **destination tenant on a different domain**, using
Microsoft Graph with app-only auth.

Because the two tenants don't trust each other, this uses **two separate Azure AD
app registrations** — one in each tenant — and acquires an independent token from
each. Files are streamed source → local temp → dest (chunked upload sessions for
large files), preserving created/modified timestamps.

> ⚠️ This tool talks to live Microsoft 365 tenants and **cannot be tested without
> real credentials + network access to Graph**. Review the setup below, run
> `--dry-run` first, and validate on a small library before a full run.

## What it migrates
- ✅ Document libraries (all, or a named subset) → same-named library on the dest
  site (created if missing)
- ✅ Full folder tree
- ✅ Files, incl. large files via upload sessions, with original timestamps

## What it does NOT migrate (by design)
- ❌ **Permissions / sharing** — identities differ across tenants; there's no 1:1
  mapping. Re-grant access on the dest side after migration.
- ❌ **Version history** — only the current version of each file is copied.
- ❌ **Non-library Lists, site pages, web parts, workflows, custom metadata
  columns** — file content is the safe, high-value core; these need separate,
  schema-aware handling and can be added later.

## Setup

### 1. App registrations (one per tenant)
In **each** tenant's Entra ID (Azure AD) → *App registrations* → *New*:

| | Source tenant app | Dest tenant app |
|---|---|---|
| API permissions (Application, **not** delegated) | `Sites.Read.All`, `Files.Read.All` | `Sites.ReadWrite.All`, `Files.ReadWrite.All` |
| Admin consent | **Grant admin consent** | **Grant admin consent** |
| Credential | client secret *or* certificate | client secret *or* certificate |

App (application) permissions require a Global/SharePoint admin to **grant admin
consent** — the app then has tenant-wide access, so scope its use carefully.

> Tighter alternative to tenant-wide `Sites.*.All`: use **`Sites.Selected`** and
> grant the app access to only the specific source/dest site (via a one-time
> `POST /sites/{id}/permissions`). Recommended if your admins prefer least
> privilege — the code paths are the same.

### 2. Install
```bash
cd sharepoint_migration
pip install -r requirements.txt        # msal, requests
```

### 3. Configure
```bash
cp config.example.json config.json      # then fill in — keep config.json out of git
```
Fill in each tenant's `tenant_id`, `client_id`, `client_secret` (or a
`certificate`), and the `site_url` of the source and dest sites. Options control
which libraries, timestamp preservation, overwrite, and chunk size.

### 4. Run
```bash
python migrate.py --config config.json --dry-run          # 1. enumerate, no writes
python migrate.py --config config.json                     # 2. migrate (resumable)
python migrate.py --config config.json --libraries "Documents,Policies"
python migrate.py --config config.json --overwrite         # replace existing dest files
```

- **Dry-run** walks the whole source tree and reports every library/folder/file
  and total bytes — nothing is written.
- **Resumable**: every copied file is recorded in `state/manifest_<src>__<dest>.json`;
  a re-run skips already-copied files. Interrupt any time and re-run.
- Logs are written to `logs/migrate_<ts>.log`.

## Layout
```
sharepoint_migration/
├── config.example.json     # copy to config.json
├── requirements.txt        # msal, requests
├── migrate.py              # orchestrator + CLI
├── engine/
│   ├── auth.py             # per-tenant app-only token (MSAL client-credentials)
│   ├── client.py           # Graph client: retry, paging, download, upload sessions
│   └── resolve.py          # site + library(drive) resolution, folder ensure
├── state/                  # resume manifests
└── logs/
```

## How it works (Graph flow)
1. `TenantAuth` acquires an app-only token per tenant (`/.default` scope).
2. Resolve each site: `GET /sites/{host}:{/sites/Name}` → site id.
3. List source libraries: `GET /sites/{id}/drives`; ensure a same-named dest
   library (create via `POST /sites/{id}/lists` with the `documentLibrary`
   template if missing).
4. Walk source `GET /drives/{id}/items/{id}/children` recursively; for each folder
   `POST …/children` a folder on the dest; for each file download
   (`…/items/{id}/content`) then upload — small (`PUT …:/name:/content`) or large
   (`createUploadSession` + ranged `PUT`s), setting `fileSystemInfo` timestamps.

## Notes / limits
- Graph **throttles** (429) — the client honors `Retry-After` and backs off; a
  very large migration will still take time. Run close to the tenants (e.g. an
  Azure VM) for throughput.
- SharePoint blocks certain file names/extensions and has path-length limits;
  such files are logged as errors and skipped (the run continues).
- Timestamps are preserved; **authorship** (created/modified *by*) cannot be set
  to a source-tenant user on the dest tenant and will show as the app/uploader.
