# Certainti Tech Administration

Internal portal for administering the technical estate: hardware assets,
software licences, people, and access requests.

## Status

This is a **working scaffold**. The UI, domain model, metrics and HTTP API are
complete and tested; persistence and authentication are deliberately not, and
are the two things to build next. See [Known limitations](#known-limitations).

## Stack

| Concern | Choice |
|---|---|
| Framework | Next.js 15 (App Router, React 19, server components) |
| Language | TypeScript, `strict` + `noUncheckedIndexedAccess` |
| Styling | Tailwind CSS v4, driven by CSS custom properties |
| Tests | Vitest |
| Persistence | In-memory (see below) |

## Getting started

```bash
npm install
npm run dev      # http://localhost:3000
```

Other scripts:

```bash
npm run build      # production build
npm start          # serve the production build
npm run lint       # ESLint
npm run typecheck  # tsc --noEmit
npm test           # Vitest
```

## What the app does

| Route | Purpose |
|---|---|
| `/` | Dashboard — headline counts, asset status split, renewals due, warranties expiring, seat utilisation |
| `/assets` | Hardware inventory, filterable by status, with warranty countdowns |
| `/licenses` | Software contracts, seat utilisation, monthly cost, renewal urgency |
| `/people` | Directory, with assets held and open requests per person |
| `/access-requests` | Approve or deny pending access requests; decided requests form an audit trail |

### HTTP API

All routes are read-only except the decision endpoint.

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/summary` | Everything the dashboard renders |
| `GET` | `/api/assets?status=` | `status` is optional; unknown values return `400` |
| `GET` | `/api/licenses` | Includes computed monthly spend |
| `GET` | `/api/people` | |
| `GET` | `/api/access-requests?status=` | `status` is optional |
| `POST` | `/api/access-requests/{id}/decision` | Body `{"decision":"approved"\|"denied"}` |

The decision endpoint returns `404` for an unknown id and `409` when the request
has already been decided. The approver is taken from the session, never from the
request body — otherwise a caller could name their own approver and the audit
trail would mean nothing.

```bash
curl -X POST http://localhost:3000/api/access-requests/req-001/decision \
  -H 'content-type: application/json' \
  -d '{"decision":"approved"}'
```

## Layout

```
app/              routes, server actions, API handlers
components/       presentational components (no data access)
lib/              domain model, seed data, store, metrics, formatting
scripts/secrets/  Azure Key Vault tooling (see docs/secrets.md)
tests/            Vitest unit tests
```

`lib/` holds every decision worth testing — severity thresholds, renewal
windows, spend arithmetic, date maths — so the pages stay thin and the rules can
be verified without rendering anything.

### Conventions worth knowing

- **Money is integer minor units.** `monthlyCostPerSeatMinor` is paise, never a
  float. It becomes a decimal only in `formatMoneyMinor`.
- **Calendar dates are `YYYY-MM-DD` strings**, parsed explicitly to UTC in
  `lib/dates.ts`. Renewals and warranties are calendar facts; anchoring them to
  an instant makes them drift by a day across timezones. Timestamps that record
  *when something happened* are full ISO-8601.
- **Status is never colour alone.** Every severity ships with a distinct icon
  shape and a text label, so it survives colour-vision deficiency, greyscale
  printing and forced-colors mode. Colours come from a validated palette defined
  as CSS custom properties in `app/globals.css`; light and dark are two selected
  sets, not an automatic inversion.
- **All data access goes through `lib/store.ts`.** No page or route reaches past
  it, which is what makes the database swap below a contained change.

## Secrets

Credentials live in one Azure Key Vault and are read from every context —
Claude Code sessions, developer shells, GitHub Actions, and deployed services —
rather than being pasted into each one. The full runbook is
[`docs/secrets.md`](docs/secrets.md).

```bash
npm run secrets:push -- --vault certainti-kv   # dry run; --apply to write
npm run secrets:check -- --vault certainti-kv  # compare vault against this env
source scripts/secrets/load.sh                 # load into the current shell
```

The inventory is declared in `scripts/secrets/manifest.mjs`; adding an entry
there makes it available everywhere at once. No command prints a secret value —
they report 12-character digests, so output is safe to paste into a ticket or a
CI log. Writing fetched secrets to a repo path that git does not ignore is
refused outright.

The Azure service principal that unlocks the vault is deliberately excluded
from the vault's own contents, since storing it there would be circular. It is
the single bootstrap credential a Claude Code session needs; CI uses OIDC and
deployed services use a managed identity, so neither stores a secret at all.

## Known limitations

These are deliberate omissions in a scaffold, not oversights — each one is a
real prerequisite before this handles anything sensitive.

1. **No persistence.** `AdminStore` holds state in process memory, seeded from
   `lib/seed.ts`. Writes are lost on restart and are not shared between server
   instances, so it will behave incorrectly behind a load balancer. Replacing it
   means reimplementing the methods on `AdminStore` and nothing else.

   The instance is pinned to `globalThis` deliberately: Next.js compiles server
   actions into a different server bundle from pages and route handlers, so the
   module is evaluated more than once per process. Without the pin, a write made
   by a server action lands on a different object than the one the page reads.

2. **No authentication or authorisation.** `lib/session.ts` returns a hard-coded
   person id that stands in for the signed-in user, and every approver recorded
   in the audit trail is therefore unverified. Anyone who can reach the app can
   approve anything. Wire up a real identity provider before deploying it
   anywhere reachable, and add an authorisation check to the decision endpoint —
   approving one's own request is currently not prevented.

3. **Single currency.** `monthlyLicenseSpend` reports the first licence's
   currency and sums across all of them. A mixed-currency estate needs
   per-currency totals and an FX rate, which the function deliberately does not
   invent.

4. **Seed data is fictional.** The people, assets and contracts in
   `lib/seed.ts` are illustrative.

## CI

`.github/workflows/ci.yml` runs lint, typecheck, tests, build, and
`npm audit --audit-level=high` on every push and pull request.

`.github/workflows/secrets-check.yml` verifies weekly that Key Vault holds every
secret the manifest declares. It authenticates over OIDC, so GitHub stores no
credential; the client/tenant/subscription ids it uses are repository
*variables*, not secrets, because they identify the app rather than
authenticate it.

Dependencies carry two `overrides` (`sharp`, `postcss`) that pull transitive
packages forward onto patched versions. Revisit them when Next.js ships releases
that depend on the fixed versions directly.
