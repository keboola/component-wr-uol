"""UOL Účetnictví writer component."""

import csv
import logging

from keboola.component.base import ComponentBase
from keboola.component.exceptions import UserException

from client.uol_client import UolClient, UolClientError
from configuration import Configuration, WriteMode
from endpoints import get_endpoint
from payload import build_payload

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
                    "uol_id": created.get("id", ""), "error_code": "", "error_message": ""}
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
            existing_id = client.lookup_by_key(endpoint.path, endpoint.lookup_key, key_value)
            if not existing_id:
                raise
            return client.update(endpoint.path, existing_id, body)

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
