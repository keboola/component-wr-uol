"""UOL Účetnictví writer component."""

from __future__ import annotations

import csv
import logging
from dataclasses import asdict, dataclass

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement, ValidationResult
from keboola.vcr import DefaultSanitizer

from client.uol_client import UolClient, UolClientError
from configuration import Configuration, WriteMode
from endpoints import ENDPOINTS, Endpoint, get_endpoint
from mapping import build_column_mapping_prefill
from payload import build_payload

# VCR sanitizers — picked up automatically by keboola.datadirtest VCR scaffold.
# DefaultSanitizer strips the Authorization header and any values marked as
# secrets in config.secrets.json.
#
# We override sensitive_fields to remove "code" from the default list because
# UOL uses "errors[].code" for human-readable error codes (e.g. "has already
# been taken", "can't be blank") which must appear verbatim in cassettes for
# log comparison to pass. OAuth's "code" grant param is not used by this writer.
VCR_SANITIZERS = [
    DefaultSanitizer(
        sensitive_fields=[
            "access_token",
            "refresh_token",
            "id_token",
            "client_id",
            "client_secret",
            "client_assertion",
            "password",
            "token",
        ],
        additional_sensitive_fields=["api_token", "email"],
    ),
]

RESULTS_TABLE = "write_results.csv"
RESULTS_COLUMNS = ["row_index", "status", "uol_id", "error_code", "error_message"]


@dataclass
class WriteResult:
    row_index: int
    status: str
    uol_id: str = ""
    error_code: str = ""
    error_message: str = ""


class Component(ComponentBase):
    def __init__(self):
        super().__init__()
        # Build config + client once. Every config field has a default, so this is
        # safe even for sync actions that don't read all fields (e.g. listEndpoints).
        self._config = Configuration(**self.configuration.parameters)
        self._client = UolClient(self._config.base_url, self._config.email, self._config.api_token)

    def run(self):
        cfg = self._config
        endpoint = get_endpoint(cfg.endpoint)
        mapping = [m.model_dump() for m in cfg.column_mapping]

        input_tables = self.get_input_tables_definitions()
        if len(input_tables) != 1:
            raise UserException(f"Exactly one input table must be mapped to this row (found {len(input_tables)}).")

        ok_count = 0
        err_count = 0
        input_path = input_tables[0].full_path
        logging.info(
            "Writing %s rows to endpoint '%s' (mode=%s)",
            self._count_rows(input_path),
            endpoint.id,
            cfg.write_mode,
        )
        results_writer = self._open_results_writer() if cfg.write_results_table else None
        try:
            # Stream the reader and write each result incrementally so neither the input
            # rows nor the result rows are all held in memory at once.
            with open(input_path, encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for index, row in enumerate(reader):
                    result = self._write_record(endpoint, mapping, row, index, results_writer)
                    if result.status == "ok":
                        ok_count += 1
                    else:
                        err_count += 1
                    if results_writer is not None:
                        results_writer.write(asdict(result))
        finally:
            if results_writer is not None:
                results_writer.close()
        logging.info("Done: %s ok, %s error", ok_count, err_count)

    @staticmethod
    def _count_rows(path: str) -> int:
        # Count data rows without materializing them, so the opening log line keeps its
        # count while the actual write stays a single streaming pass.
        with open(path, encoding="utf-8") as fh:
            return max(sum(1 for _ in csv.reader(fh)) - 1, 0)

    def _write_record(
        self,
        endpoint: Endpoint,
        mapping: list[dict],
        row: dict,
        index: int,
        results_writer: _ResultsWriter | None = None,
    ) -> WriteResult:
        cfg = self._config
        client = self._client
        # build_payload raises UserException for bad row data (invalid nested JSON, missing
        # mapped column). That's a per-row data problem, so when fail_on_error is false it must
        # be logged and skipped like an API error — otherwise one bad row aborts the whole job.
        # When fail_on_error is true we let it propagate untouched (it already carries a clear
        # user-facing message). Config-level errors (e.g. missing upsert lookup key, raised
        # inside _upsert) are NOT caught here and always abort, as before.
        if cfg.fail_on_error:
            body = build_payload(row, mapping, endpoint)
        else:
            try:
                body = build_payload(row, mapping, endpoint)
            except UserException as exc:
                logging.warning("Row %s skipped — invalid payload: %s", index, exc)
                return WriteResult(row_index=index, status="error", error_code="payload_error", error_message=str(exc))
        try:
            if cfg.write_mode == WriteMode.upsert:
                created = self._upsert(client, endpoint, body)
            else:
                created = client.create(endpoint.path, body)
            return WriteResult(row_index=index, status="ok", uol_id=client.extract_id(created))
        except UolClientError as exc:
            if cfg.fail_on_error:
                # Write the failing row's error result to the results table BEFORE raising so
                # the audit is never silent about the failure (write_always=True uploads partial
                # results even on abort, so the error entry must be flushed first).
                error_result = WriteResult(
                    row_index=index, status="error", error_code=exc.code, error_message=exc.message
                )
                if results_writer is not None:
                    results_writer.write(asdict(error_result))
                raise UserException(f"Row {index}: API error [{exc.code}] {exc.message}")
            logging.warning("Row %s failed: [%s] %s", index, exc.code, exc.message)
            return WriteResult(row_index=index, status="error", error_code=exc.code, error_message=exc.message)

    @staticmethod
    def _upsert(client: UolClient, endpoint: Endpoint, body: dict) -> dict:
        try:
            return client.create(endpoint.path, body)
        except UolClientError as exc:
            if not client.is_conflict(exc):
                raise
            key_value = body.get(endpoint.lookup_key)
            if key_value is None:
                raise UserException(
                    f"Upsert on '{endpoint.id}' requires the lookup key '{endpoint.lookup_key}' "
                    f"to be mapped in the column mapping."
                )
            existing_id = client.lookup_by_key(endpoint.path, endpoint.lookup_key, key_value)
            if not existing_id:
                raise
            return client.update(endpoint.path, existing_id, body)

    @sync_action("testConnection")
    def test_connection(self) -> ValidationResult:
        try:
            self._client.ping()
        except UolClientError as exc:
            raise UserException(f"Connection failed: [{exc.code}] {exc.message}")
        return ValidationResult("Connection successful.")

    @sync_action("listEndpoints")
    def list_endpoints(self) -> list[SelectElement]:
        return [SelectElement(value=e.id, label=e.label) for e in ENDPOINTS.values()]

    @sync_action("loadColumnMapping")
    def load_column_mapping(self) -> dict:
        # The raw params dict is round-tripped back to the UI (it must preserve arbitrary
        # UI-only fields), so we keep it here rather than rebuilding it from the typed config.
        params = self.configuration.parameters
        endpoint_id = self._config.endpoint
        if not endpoint_id:
            raise UserException("Select an endpoint before loading the column mapping.")
        endpoint = get_endpoint(endpoint_id)
        input_mappings = self.configuration.tables_input_mapping
        if len(input_mappings) != 1:
            raise UserException(f"Map exactly one input table to this row first (found {len(input_mappings)}).")
        columns = self._get_input_columns(input_mappings[0].source)
        existing = params.get("column_mapping", [])
        mapping = build_column_mapping_prefill(columns, list(endpoint.fields), existing)
        data = dict(params)
        data["column_mapping"] = mapping
        data["_metadata_"] = {"uol_fields": self._fields_metadata(endpoint)}
        return {"type": "data", "data": data}

    @staticmethod
    def _fields_metadata(endpoint: Endpoint) -> list[dict]:
        out = []
        for f in endpoint.fields:
            required = f in endpoint.required_fields
            label = f"{f} (required)" if required else f
            out.append({"field_name": f, "label": label})
        return out

    def _get_input_columns(self, source: str) -> list[str]:
        # Callers (run / loadColumnMapping) already enforce exactly one mapped input table.
        # The loaded TableDefinition's on-disk name is the mapping destination, not the
        # storage `source`, so match by name when possible and otherwise take the sole table.
        tables = self.get_input_tables_definitions()
        if not tables:
            raise UserException("No input table columns found. Map an input table first.")
        for table in tables:
            if table.name == source:
                return list(table.columns)
        return list(tables[0].columns)

    def _open_results_writer(self) -> _ResultsWriter:
        # create_out_table_definition signature (confirmed against keboola-component):
        #   (name, is_sliced=False, destination='', primary_key=None, schema=None,
        #    incremental=None, ..., write_always=False, ...)
        # schema accepts list[str] of plain column names (SCHEMA_TYPE = dict|OrderedDict|list[str])
        table = self.create_out_table_definition(
            RESULTS_TABLE,
            primary_key=["row_index"],
            incremental=True,
            schema=RESULTS_COLUMNS,
            write_always=True,
            has_header=True,
        )
        return _ResultsWriter(table, self.write_manifest)


class _ResultsWriter:
    """Streams write results to the results CSV incrementally and writes the manifest on close."""

    def __init__(self, table, write_manifest):
        self._table = table
        self._write_manifest = write_manifest
        self._fh = open(table.full_path, "w", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._fh, fieldnames=RESULTS_COLUMNS)
        self._writer.writeheader()

    def write(self, row: dict) -> None:
        self._writer.writerow(row)

    def close(self) -> None:
        self._fh.close()
        self._write_manifest(self._table)


if __name__ == "__main__":
    try:
        comp = Component()
        comp.execute_action()
    except UserException as exc:
        logging.exception(exc)
        exit(1)
    except Exception as exc:
        logging.exception(exc)
        exit(2)
