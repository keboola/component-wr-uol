UOL Účetnictví writer pushes rows from Keboola Storage tables into the [UOL Účetnictví](https://www.uol.cz) cloud accounting system through its [REST API](https://api.uol.cz).

The component is configured with one configuration row per write target. Each row selects a UOL endpoint (contacts, sales invoices, purchase invoices, products, contact bank accounts), links one input table, and maps the table's columns to the endpoint's fields. Every input row is sent to UOL as a create or upsert call.

## Features

- **Per-endpoint configuration rows** — each row writes one input table to one UOL endpoint, with its own column mapping and write mode.
- **Explicit column mapping** with assisted setup — a sync action lists the endpoint's fields and auto-maps your input columns to them (with fuzzy name matching), which you can then adjust.
- **Create or upsert** — for endpoints that expose a unique lookup key (e.g. contacts via `external_id`), upsert creates new records and updates existing ones. Endpoints without a lookup key are create-only.
- **Nested data** — columns can carry JSON arrays for nested structures such as invoice items or contact addresses.
- **Optional results table** — an audit table reporting the per-row outcome (success or error) for inspection downstream.

## Authentication

Authentication uses HTTP Basic auth with the API user's email and an API token. Generate the token in your UOL system under *Settings ▸ Technical ▸ API tokens* and enable the "REST API" permission for the user.
