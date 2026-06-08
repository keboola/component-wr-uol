"""UOL Účetnictví writer component."""

import csv
import logging

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement, ValidationResult
from keboola.vcr import DefaultSanitizer

from client.uol_client import UolClient, UolClientError
from configuration import Configuration, WriteMode
from endpoints import ENDPOINTS, get_endpoint
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
        sensitive_fields=["access_token", "refresh_token", "id_token", "client_id",
                          "client_secret", "client_assertion", "password", "token"],
        additional_sensitive_fields=["api_token", "email"],
    ),
]

RESULTS_TABLE = "write_results.csv"
RESULTS_COLUMNS = ["row_index", "status", "uol_id", "error_code", "error_message"]


class Component(ComponentBase):
    def __init__(self):
        super().__init__()

    def _build_client(self, cfg: Configuration) -> UolClient:
        return UolClient(cfg.base_url, cfg.email, cfg.api_token)

    def run(self):
        cfg = Configuration(**self.configuration.parameters)
        if cfg.debug:
            logging.getLogger().setLevel(logging.DEBUG)

        endpoint = get_endpoint(cfg.endpoint)
        mapping = [m.model_dump() for m in cfg.column_mapping]

        input_tables = self.get_input_tables_definitions()
        if len(input_tables) != 1:
            raise UserException(
                f"Exactly one input table must be mapped to this row (found {len(input_tables)})."
            )

        client = self._build_client(cfg)
        results: list[dict] = []
        with open(input_tables[0].full_path, encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for index, row in enumerate(reader):
                results.append(self._write_record(client, cfg, endpoint, mapping, row, index))

        if cfg.write_results_table:
            self._write_results_table(results)

    def _write_record(self, client, cfg, endpoint, mapping, row, index) -> dict:
        try:
            body = build_payload(row, mapping, endpoint)
            if cfg.write_mode == WriteMode.upsert:
                created = self._upsert(client, endpoint, body)
            else:
                created = client.create(endpoint.path, body)
            return {"row_index": index, "status": "ok",
                    "uol_id": client.extract_id(created), "error_code": "", "error_message": ""}
        except UolClientError as exc:
            if cfg.fail_on_error:
                raise UserException(f"Row {index}: API error [{exc.code}] {exc.message}")
            logging.warning("Row %s failed: [%s] %s", index, exc.code, exc.message)
            return {"row_index": index, "status": "error", "uol_id": "",
                    "error_code": exc.code, "error_message": exc.message}

    def _upsert(self, client, endpoint, body) -> dict:
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
        cfg = Configuration(**self.configuration.parameters)
        try:
            self._build_client(cfg).ping()
        except UolClientError as exc:
            raise UserException(f"Connection failed: [{exc.code}] {exc.message}")
        return ValidationResult("Connection successful.")

    @sync_action("listEndpoints")
    def list_endpoints(self) -> list[SelectElement]:
        return [SelectElement(value=e.id, label=e.label) for e in ENDPOINTS.values()]

    @sync_action("listFields")
    def list_fields(self) -> list[dict]:
        endpoint_id = self.configuration.parameters.get("endpoint")
        if not endpoint_id:
            raise UserException("Select an endpoint before loading its fields.")
        endpoint = get_endpoint(endpoint_id)
        return self._fields_metadata(endpoint)

    @sync_action("loadColumnMapping")
    def load_column_mapping(self) -> dict:
        params = self.configuration.parameters
        endpoint_id = params.get("endpoint")
        if not endpoint_id:
            raise UserException("Select an endpoint before loading the column mapping.")
        endpoint = get_endpoint(endpoint_id)
        input_mappings = self.configuration.tables_input_mapping
        if len(input_mappings) != 1:
            raise UserException(
                f"Map exactly one input table to this row first (found {len(input_mappings)})."
            )
        columns = self._get_input_columns(input_mappings[0].source)
        existing = params.get("column_mapping", [])
        mapping = build_column_mapping_prefill(columns, list(endpoint.fields), existing)
        data = dict(params)
        data["column_mapping"] = mapping
        data["_metadata_"] = {"uol_fields": self._fields_metadata(endpoint)}
        return {"type": "data", "data": data}

    @staticmethod
    def _fields_metadata(endpoint) -> list[dict]:
        out = []
        for f in endpoint.fields:
            required = f in endpoint.required_fields
            label = f"{f} (required)" if required else f
            out.append({"field_name": f, "label": label})
        return out

    def _get_input_columns(self, source: str) -> list[str]:
        for table in self.get_input_tables_definitions():
            if getattr(table, "name", None) == source or getattr(table, "source", None) == source:
                return list(table.columns)
        tables = self.get_input_tables_definitions()
        if tables:
            return list(tables[0].columns)
        raise UserException("No input table columns found. Map an input table first.")

    def _write_results_table(self, results: list[dict]) -> None:
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
        )
        with open(table.full_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=RESULTS_COLUMNS)
            writer.writeheader()
            for r in results:
                writer.writerow(r)
        self.write_manifest(table)


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
