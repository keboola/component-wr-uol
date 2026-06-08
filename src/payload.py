"""Build a UOL API request body from one input-table row + a column mapping.

CSV values are already strings, which satisfies UOL's "booleans as strings"
quirk for scalar fields with no extra coercion. Only columns mapped to an
endpoint's nested fields are JSON-parsed into arrays/objects.
"""

import json

from keboola.component.exceptions import UserException

from endpoints import Endpoint


def build_payload(row: dict, column_mapping: list[dict], endpoint: Endpoint) -> dict:
    payload: dict = {}
    for entry in column_mapping:
        source = entry.get("source", "")
        destination = entry.get("destination", "")
        if not destination:
            continue  # unmapped column → dropped
        if source not in row:
            raise UserException(
                f"Mapped source column '{source}' not found in input table for "
                f"endpoint '{endpoint.id}'."
            )
        value = row[source]
        if destination in endpoint.nested_fields:
            if value == "" or value is None:
                payload[destination] = []
                continue
            try:
                payload[destination] = json.loads(value)
            except json.JSONDecodeError as exc:
                raise UserException(
                    f"Column '{source}' mapped to nested field '{destination}' is "
                    f"not valid JSON: {exc}"
                )
        else:
            payload[destination] = value
    return payload
