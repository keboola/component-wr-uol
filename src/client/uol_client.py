"""HTTP client for the UOL Účetnictví REST API.

Wraps keboola.http_client.HttpClient for Basic auth + retry/backoff (incl. 429).
All API-level errors surface as UolClientError carrying the UOL error code.

DEMO-confirmed behaviour (Task 7):
- List responses use the key "items", not "data".
- Resources have no "id" field; the unique slug lives in _meta.href (last path segment)
  and is duplicated as a resource-specific field (e.g. contact_id, product_id).
- Duplicate-create returns HTTP 422 with body:
    {"message": "Validation failed",
     "errors": [{"resource": "...", "field": "...", "code": "has already been taken"}]}
  UOL does NOT use a numeric error code like "0005"/"0006"; conflict detection
  is therefore based on status 422 only (status_code in _CONFLICT_STATUSES) or the
  sentinel string "has already been taken" in errors[].code.
"""

from typing import Any

import requests
from keboola.http_client import HttpClient

# UOL conflict/duplicate detection (confirmed on DEMO, Task 7).
# The API returns HTTP 422 with errors[].code == "has already been taken".
# There is no numeric code in the response body.
_CONFLICT_STATUSES = {422}
_CONFLICT_CODES = {"has already been taken"}


class UolClientError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(f"[{code}] {message}")


class UolClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self._http = HttpClient(
            base_url if base_url.endswith("/") else base_url + "/",
            max_retries=5,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            default_http_header={"Accept": "application/json"},
            auth=(email, api_token),
        )

    def _request(self, method: str, endpoint_path: str, **kwargs) -> Any:
        # Thin seam over HttpClient so unit tests can mock one method.
        # The installed library exposes _request_raw (not request_raw).
        try:
            return self._http._request_raw(method, endpoint_path, **kwargs)  # noqa: SLF001
        except requests.exceptions.RequestException as e:
            raise UolClientError(
                code="connection_error",
                message=f"Could not reach UOL API: {e}",
                status=None,
            ) from e

    @staticmethod
    def _parse_error(response: Any) -> UolClientError:
        """Parse a UOL error response.

        UOL uses two error shapes:
        1. Validation errors (422): {"message": "...", "errors": [{"code": "..."}]}
        2. Other errors: may vary; fall back to {"message": "..."} with no code.
        """
        try:
            body = response.json()
            # Shape 1: Rails-style validation errors
            errors = body.get("errors") or []
            if errors and isinstance(errors, list):
                first = errors[0]
                code = first.get("code", "unknown")
                field = first.get("field", "")
                msg = body.get("message", "Validation failed")
                if field:
                    msg = f"{msg} (field: {field})"
                return UolClientError(code=code, message=msg, status=response.status_code)
            # Shape 2: legacy {"error": {"code": ..., "message": ...}}
            err = body.get("error", {})
            if err:
                return UolClientError(
                    code=err.get("code", "unknown"),
                    message=err.get("message", "Unknown error"),
                    status=response.status_code,
                )
            # Shape 3: flat root-level {"status": "401", "code": "0002", "message": "..."}
            root_code = body.get("code")
            root_message = body.get("message")
            if root_code is not None and not isinstance(root_code, dict):
                return UolClientError(
                    code=str(root_code),
                    message=root_message if root_message is not None else "Unknown error",
                    status=response.status_code,
                )
            if root_message is not None:
                return UolClientError(
                    code="unknown",
                    message=root_message,
                    status=response.status_code,
                )
            # Fallback
            return UolClientError(
                code="unknown",
                message="Unknown error",
                status=response.status_code,
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            return UolClientError(
                code="unknown",
                message=f"Unexpected error response (HTTP {response.status_code}): {getattr(response, 'text', '')[:300]}",
                status=response.status_code,
            )

    def _handle(self, response: Any) -> dict:
        if response.status_code >= 400:
            raise self._parse_error(response)
        return response.json()

    def ping(self) -> None:
        self._handle(self._request("GET", "v1/ping"))

    def create(self, path: str, payload: dict) -> dict:
        return self._handle(self._request("POST", path.lstrip("/"), json=payload))

    def update(self, path: str, record_id: str, payload: dict) -> dict:
        return self._handle(self._request("PATCH", f"{path.lstrip('/')}/{record_id}", json=payload))

    @staticmethod
    def extract_id(body: dict) -> str:
        """UOL records have no `id` field; the slug is the last path segment of _meta.href."""
        href = (body.get("_meta") or {}).get("href", "")
        return href.rsplit("/", 1)[-1] if href else ""

    def lookup_by_key(self, path: str, key_field: str, value: str) -> str | None:
        """Look up a resource by a filterable unique key.

        Returns the resource slug (last segment of _meta.href), which is the
        value accepted by update() / PATCH. Returns None if not found.

        DEMO-confirmed: list responses use "items" (not "data").
        Resources have no "id" field; the unique identifier is the slug from _meta.href.
        """
        response = self._request("GET", path.lstrip("/"), params={key_field: value, "per_page": 1})
        body = self._handle(response)
        # UOL list responses use "items" key (confirmed on DEMO, Task 7)
        data = body.get("items") or []
        if data:
            slug = self.extract_id(data[0])
            if slug:
                return slug
        return None

    @staticmethod
    def is_conflict(error: UolClientError) -> bool:
        return error.status in _CONFLICT_STATUSES or error.code in _CONFLICT_CODES
