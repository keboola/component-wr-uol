"""HTTP client for the UOL Účetnictví REST API.

Wraps keboola.http_client.HttpClient for Basic auth + retry/backoff (incl. 429).
All API-level errors surface as UolClientError carrying the UOL error code.
"""

from typing import Any

from keboola.http_client import HttpClient

# UOL conflict/duplicate error codes (confirm exact codes on DEMO in Task 7).
_CONFLICT_CODES = {"0005", "0006"}
_CONFLICT_STATUSES = {409, 422}


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
        return self._http._request_raw(method, endpoint_path, **kwargs)  # noqa: SLF001

    @staticmethod
    def _parse_error(response: Any) -> UolClientError:
        try:
            body = response.json()
            err = body.get("error", {})
            return UolClientError(
                code=err.get("code", "unknown"),
                message=err.get("message", "Unknown error"),
                status=response.status_code,
            )
        except Exception:
            return UolClientError(code="unknown", message="Unparseable error", status=response.status_code)

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

    def lookup_by_key(self, path: str, key_field: str, value: str) -> str | None:
        response = self._request("GET", path.lstrip("/"), params={key_field: value, "per_page": 1})
        body = self._handle(response)
        data = body.get("data") or []
        if data:
            return data[0].get("id")
        return None

    @staticmethod
    def is_conflict(error: UolClientError) -> bool:
        return error.status in _CONFLICT_STATUSES or error.code in _CONFLICT_CODES
