# wr-uol — Design Spec

> Type: writer
> Component ID: keboola.wr-uol
> Status: draft
> Date: 2026-06-08

## 1. Overview & source system

`wr-uol` writes data from Keboola Storage tables into **UOL Účetnictví**, a Czech cloud
accounting/ERP SaaS (https://www.uol.cz). For each writable object the user picks an API endpoint,
links one input table to it, and maps the table's columns to the endpoint's fields; the component
sends each row as a create/update API call.

- **Target system:** UOL Účetnictví REST/JSON API — docs at https://api.uol.cz, OpenAPI at
  https://api.uol.cz/openapi.yaml.
- **Primary use case:** push accounting master data and documents (contacts, sales/purchase
  invoices, products, bank accounts, etc.) from a Keboola pipeline into UOL, so an accounting
  workflow can be fed automatically from upstream systems (e-shop, CRM, billing).

## 2. Keboola mapping

- **Input tables → API writes.** One input table per config row; each data row → one API
  create/update call to the selected endpoint.
- **Config rows, one row per endpoint/table.** Per Keboola convention, a writer handling several
  independent objects uses config rows — each row selects one UOL endpoint, links one input table,
  and carries its own column mapping and write mode. Rows can be enabled/run/retried independently.
  Connection credentials live once at config level. *Override note:* not a multipick — object-level
  granularity per row is the convention.
- **No incremental state.** This is a writer; it reads Keboola input tables (the platform's input
  mapping already controls incremental delivery via "changed rows only"). The component itself keeps
  no `state.json` watermark. Idempotency comes from the per-row **write mode** (see §4), not state.
- **Secrets** → `#api_token` at config level (`#`-prefixed, platform-encrypted).
- **Sync actions** (see §5): `testConnection`, `listEndpoints`, `listFields`, `loadColumnMapping`
  (fuzzy auto-map).
- **Output:** a writer produces no Storage output tables in the normal sense. It optionally writes a
  small **results/errors table** to `out/tables` (one row per attempted record with status + error
  message) so failures are inspectable downstream. Default bucket naming applies if written.

## 3. Authentication & connection

- **Auth: HTTP Basic.** Username = user email, password = API token. This is the only method UOL
  offers for the REST API, so there's no alternative to weigh. Sent on every request as a standard
  `Authorization: Basic` header.
- **Connection: REST/JSON over HTTPS.** Single API surface; no SOAP/SQL alternative.
- **Customer-specific base URL.** The host encodes the environment + customer:
  - DEMO (shared sandbox): `https://test.demo.uol.cz/api`
  - Customer sandbox: `https://{customerId}.sandbox.uol.cz/api`
  - Production: `https://{customerId}.ucetnictvi.uol.cz/api`

  The component takes an **environment** choice + a **customer ID** and builds the base URL, OR
  accepts a full base URL directly (DEMO needs no customer ID). v1: an `environment` enum
  (`demo` / `sandbox` / `production`) plus `customer_id` (ignored for `demo`).
- **Provisioning (headless-friendly):** the customer logs into their UOL system →
  *Settings ▸ Technical ▸ API tokens*, enables the "REST API" permission on a user, and copies the
  token + that user's email. No app registration, no OAuth dance, no admin approval flow beyond
  granting the permission. Tokens are long-lived. This is fully self-service.
- **Blockers / access:** **None blocking.** A public DEMO instance with working credentials exists
  (`demo@ucetnictvi-on-line.cz` / token `3R1Cc_wzcSuq02Wsh1-uww` against `test.demo.uol.cz`), which
  we use for VCR recording and cf-dev smoke testing. The user also has their own test instance.

## 4. Data model & endpoints

**Scope: all writable objects, generically.** Rather than hard-coding per-object logic, the
component treats every endpoint uniformly: select endpoint → map columns → send rows. The endpoint
list is curated (the writable POST/PATCH resources of the API), exposed via the `listEndpoints` sync
action. v1 ships the full writable set the API documents:

| Endpoint | Path | Notes |
|---|---|---|
| Contacts | `/v1/contacts` | upsertable via `external_id`; supports PATCH |
| Sales invoices | `/v1/sales_invoices` | nested `items[]` |
| Purchase invoices | `/v1/purchase_invoices` | nested `items[]` |
| Products | `/v1/products` | master data |
| Contact bank accounts | `/v1/contact_bank_accounts` | linked to a contact |
| Cashes (income/disbursement) | `/v1/cashes/...` | document writes |

The curated list lives in a single module-level registry (endpoint id → path, label, key field,
nested-array field names if any). Adding an endpoint later = one registry entry, no new code path.

- **Nested fields (Axis 1 decision — JSON column):** for endpoints with nested arrays (invoice
  `items[]`, contact `addresses[]`), the user maps a single input column containing a **JSON array
  string**; the component `json.loads()` it and embeds it in the payload. The transformation layer is
  where users shape nested data. Scalar fields map 1:1.
- **Column-to-field mapping (Axis 2 decision — explicit mapping, always):** every config row carries
  an explicit `column_mapping` (array of `{source, destination}`). There is **no** implicit
  "column name = API field" mode. A `loadColumnMapping` sync action pre-fills the mapping by
  fuzzy-matching input columns to the endpoint's fields (see §5). This mirrors the established CF
  writer pattern (wr-abra-flexi, wr-oracle-ebs, sage-intacct-writer).
- **Write mode (Axis 3 decision — POST-then-fallback, per-row):** each row chooses its write strategy:
  - `create` — always POST; on conflict, record the error and continue (or fail, per `fail_on_error`).
  - `upsert` — POST first; if the API rejects as a duplicate (e.g. existing `external_id`), fall back
    to PATCH on the existing record. **Risk:** UOL's error schema (`{error:{code,message}}`) does not
    reliably return the conflicting record's `id`. Where it does not, upsert degrades to a
    lookup-then-PATCH (GET by `external_id` → PATCH) for endpoints that support a lookup filter
    (contacts via `external_id`); for endpoints with no lookup key, `upsert` is unavailable and the
    UI hides it. This is the one place POST-then-fallback needs a per-endpoint capability flag in the
    registry. See §9.
- **Pagination:** only relevant to the `listFields`/lookup reads, not the writes. UOL uses offset
  pagination (`page`/`per_page`, max 250) with a `_meta.pagination` block. The lookup-by-`external_id`
  path uses a filtered single-page GET.
- **Rate limits:** 30 requests / 10 s for general endpoints, 10 requests / 10 s for `/receivables`.
  HTTP 429 on exceed, 30 s throttle window. The client implements **per-request throttling +
  exponential backoff on 429** (respect `Retry-After` if present), with a small concurrency of 1
  (sequential writes) to stay well under the limit. Batch size is configurable per row.
- **Bulk/async export:** none — writes are per-record synchronous POST/PATCH.

## 5. Configuration & schema

> **Handoff:** the actual `configSchema.json` / `configRowSchema.json` is built by
> `component-build-ui`. This section specifies the fields; it does not write the JSON.

**Config-level (root) parameters — connection, entered once:**
- `environment` — enum `demo | sandbox | production` (default `demo`). Decides URL template.
- `customer_id` — string, required for `sandbox`/`production`, ignored for `demo`.
- `email` — string, the API user's email (Basic auth username).
- `#api_token` — secret string (Basic auth password), `#`-prefixed → encrypted.
- `debug` — boolean, verbose logging.

**Row-level parameters — one per endpoint/table:**
- `endpoint` — string, populated by `listEndpoints` dropdown (the curated writable set).
- `write_mode` — enum `create | upsert` (upsert shown only when the endpoint supports a lookup key).
- `column_mapping` — array of `{source, destination}`. `source` read-only (from input columns),
  `destination` a dropdown fed from `_metadata_.uol_fields` populated by `loadColumnMapping`.
- `batch_size` — int, default 100, bounds 1..250 (matches API `per_page` ceiling for reads;
  writes are per-record but batch controls logging/error-table flush cadence).
- `fail_on_error` — boolean, default false. False → log per-record errors to the results table and
  continue; true → raise `UserException` on first failure.

**Sync actions:**
- `testConnection` — calls `GET /v1/ping` with the configured Basic auth; returns
  `ValidationResult("Connection successful.")` or raises `UserException` with the API error message.
- `listEndpoints` — returns `list[SelectElement]` from the curated endpoint registry.
- `listFields` — for the selected endpoint, returns its writable field names (label includes
  `(required)` for mandatory fields). Backed by a static per-endpoint field list in the registry
  (UOL has no field-introspection endpoint, so fields are curated from the OpenAPI spec). Stored in
  `_metadata_.uol_fields` for the mapping dropdown.
- `loadColumnMapping` — **the fuzzy auto-map action.** Requires endpoint selected + exactly one input
  table linked. Reads the input table's columns, the endpoint's fields, preserves any existing
  mappings, and fuzzy-matches the rest. Returns `{"type":"data","data":{...config..., "_metadata_":
  {"uol_fields":[...]}}}`. Fuzzy match is the CF-standard custom 3-tier: exact → case-insensitive →
  normalized (strip `_`,`-`,space,`.` then lowercase). No external library.

## 6. Code architecture

```
src/
  component.py          # Component(ComponentBase): run() orchestrator + @sync_action methods
  configuration.py      # Pydantic: Configuration (root) + RowConfiguration + ColumnMapping
  client/
    uol_client.py       # UolClient: HTTP, Basic auth, throttle/backoff, ping/create/update/lookup
  endpoints.py          # curated endpoint registry: id → {path, label, key_field, nested_fields, fields[], supports_upsert}
```

- **Client separation:** `UolClient` owns all HTTP — base-URL assembly, Basic auth header, the
  429 throttle/backoff, and typed methods (`ping()`, `create(endpoint, payload)`,
  `update(endpoint, id, payload)`, `lookup_by_external_id(endpoint, value)`). It raises a typed
  `UolClientError` on API errors carrying the UOL error code + message. Nothing UI/Keboola-specific
  leaks in.
- **`run()` as thin orchestrator:**
  1. Parse + validate config (Pydantic, fail early).
  2. Resolve the endpoint from the registry; validate the column mapping against its fields.
  3. Read the single input table.
  4. For each row: apply column mapping → build payload (deserialize JSON columns for nested
     fields, coerce booleans to strings per UOL's quirk) → call client `create`/`upsert`.
  5. Collect per-record results; write the results/errors table; honor `fail_on_error`.
- **Error handling:**
  - `UserException` (exit 1): bad/missing config, auth failure (401/`0002`), invalid customer ID
    (`0003`), unknown endpoint, mapping referencing a non-existent column, malformed JSON in a
    nested column, and — when `fail_on_error=true` — the first API rejection.
  - Unexpected (exit 2): everything else (network stack errors not covered by retry, programming
    errors).
- **Key dependencies:** `keboola.component` (ComponentBase, sync actions, ValidationResult,
  SelectElement), `httpx` or `requests` for HTTP, `pydantic` v2 for config. No UOL SDK exists
  (their only published client is Ruby), so a plain REST client is correct. No fuzzy-match library
  (custom 3-tier, per CF convention).

## 7. Testing

- **Datadir tests** (`tests/functional/`, keboola.datadirtest):
  - `create_contact_ok` — one contact row, `create` mode, happy path → success results table.
  - `create_invoice_nested_items` — sales invoice with a JSON `items` column → payload nesting works.
  - `upsert_contact_existing` — `upsert` mode where external_id exists → falls back to PATCH.
  - `missing_required_field` — mapping omits a required field → `UserException`, exit 1.
  - `bad_json_nested_column` — malformed JSON in nested column → `UserException`, exit 1.
  - `auth_failure` — bad token → exit 1 with UOL `0002` message.
  - `fail_on_error_true` — API rejects a record with `fail_on_error=true` → exit 1.
  - `fail_on_error_false` — same rejection with false → exit 0, error captured in results table.
- **VCR strategy:** record real HTTP against the public DEMO (`test.demo.uol.cz`,
  `demo@ucetnictvi-on-line.cz` + demo token) with `keboola.datadirtest` + VCR. Record: `ping`, a
  contact create, an invoice create with items, an upsert (create→409/duplicate→patch), and an auth
  failure. **Sanitizers:** scrub the `Authorization` header (Basic blob), the api token value, and
  the demo email from request/response before commit. One cassette per datadir case.
- **Sync action tests:** unit tests for `loadColumnMapping` fuzzy matching (exact / case-insensitive
  / normalized / no-match → blank), `listEndpoints`/`listFields` shape, and `testConnection`
  success + failure (VCR-backed `ping`).
- **Seed payloads:** the OpenAPI request schemas in §1 docs + the research in this spec seed the
  fixture payloads; the DEMO instance provides real response shapes for cassettes.

## 8. Deployment & validation (cf-dev project)

- Build an image from the `initial-implementation` branch (push branch → CI builds a branch-tagged
  image).
- Via kbagent: create a `keboola.wr-uol` config in **cf-dev**, override the image tag to the branch
  build, set DEMO credentials at config level, add one config row (endpoint `contacts`, a small
  input table, a column mapping), and run a job.
- **Success looks like:** job status `success`; the contact is created in the DEMO instance; the
  results table shows one row with `status=ok`; resolved image tag matches the
  `initial-implementation` build (not a stable release).

## 9. Open risks & blockers

1. **Upsert reliability (medium).** UOL's error response may not return the conflicting record's
   `id`, so pure POST-then-fallback can't always recover the id to PATCH. Mitigation: per-endpoint
   `supports_upsert` flag + lookup-by-`external_id` fallback for endpoints that have a lookup key
   (contacts); hide `upsert` for endpoints that don't. Confirm against DEMO during implementation
   which endpoints return a usable conflict id.
2. **Field lists are curated, not introspected (low).** UOL has no "describe endpoint fields" API, so
   `listFields` returns a hand-maintained list derived from the OpenAPI spec. Risk of drift if UOL
   adds fields. Mitigation: keep the registry in one module; document that it tracks the OpenAPI spec.
3. **Boolean-as-string quirk (low).** UOL requires booleans in POST bodies as `"true"`/`"false"`
   strings. The payload builder must coerce; covered by a datadir test.
4. **Rate limits on large tables (low).** 30 req/10 s with per-record writes caps throughput
   (~3 rec/s sustained). Acceptable for accounting-volume data; documented. Batch/throttle handles it.
5. **Nested-array field discovery (low).** Which columns are "JSON nested" is declared in the
   registry per endpoint; a mapping that points a nested field at a non-JSON column fails at parse
   time with a clear `UserException`.
