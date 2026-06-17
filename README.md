wr-uol
=============

Writes data from Keboola Storage tables into the [UOL Účetnictví](https://www.uol.cz) cloud
accounting system through its [REST API](https://api.uol.cz).

The component is configured with one configuration row per write target. Each row selects a UOL
endpoint, links one input table, and maps the table's columns to the endpoint's fields. Every input
row is sent to UOL as a create or upsert call.

**Table of Contents:**

[TOC]

Prerequisites
=============

Generate an API token in your UOL system under *Settings ▸ Technical ▸ API tokens* and enable the
**REST API** permission for the user. You authenticate with that user's email and the API token.

Features
========

| **Feature**               | **Description**                                                          |
|---------------------------|--------------------------------------------------------------------------|
| Row-Based Configuration   | One configuration row per endpoint / input table.                        |
| Explicit Column Mapping   | Map input columns to UOL fields, with an assisted fuzzy auto-map action. |
| Create / Upsert           | Create new records, or upsert where the endpoint has a unique lookup key.|
| Nested Data               | JSON-array columns for nested structures (invoice items, addresses).     |
| Results Table             | Optional per-row audit table (status, error, created record id).         |
| Test Connection           | Validate credentials from the UI before running.                         |

Supported Endpoints
===================

Contacts, Sales invoices, Purchase invoices, Products, Contact bank accounts. The list is curated
from the UOL API; if you need additional endpoints, submit a request to
[ideas.keboola.com](https://ideas.keboola.com/).

Configuration
=============

Connection (root)
-----------------
- **Environment** — `sandbox` or `production`.
- **Customer ID** — your UOL customer ID (the subdomain of your UOL instance). Required.
- **API User Email** — the API user's email (Basic auth username).
- **API Token** — the API token (encrypted).

Write target (row)
------------------
- **Endpoint** — the UOL endpoint to write to (loaded via a sync action).
- **Write Mode** — `create`, or `upsert` for endpoints that expose a unique lookup key.
- **Column Mapping** — map each input column to a UOL field. Use *Load / Re-load Column Mapping* to
  auto-populate it from the input table and the endpoint's fields (fuzzy-matched), then adjust.
- **Batch Size**, **Write Results Table**, **Fail on First Error**.

Output
======

When **Write Results Table** is enabled, the component writes one row per attempted record
(`row_index`, `status`, `uol_id`, `error_code`, `error_message`) so outcomes and errors are
inspectable downstream.

Development
-----------

To customize the local data folder path, replace the `CUSTOM_FOLDER` placeholder with your desired path in the `docker-compose.yml` file:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    volumes:
      - ./:/code
      - ./CUSTOM_FOLDER:/data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Clone this repository, initialize the workspace, and run the component using the following
commands:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
git clone https://github.com/keboola/component-wr-uol.git
cd component-wr-uol
docker-compose build
docker-compose run --rm dev
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the test suite and perform lint checks using this command:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
docker-compose run --rm test
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Integration
===========

For details about deployment and integration with Keboola, refer to the
[deployment section of the developer
documentation](https://developers.keboola.com/extend/component/deployment/).
