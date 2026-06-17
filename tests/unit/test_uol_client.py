from unittest import mock

import pytest
import requests

from client.uol_client import UolClient, UolClientError


def _client() -> UolClient:
    return UolClient(base_url="https://test.demo.uol.cz/api", email="e@x.cz", api_token="t")


def _resp(status: int, body: dict) -> mock.Mock:
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = body
    return r


def test_create_returns_parsed_body_on_2xx():
    c = _client()
    with mock.patch.object(c, "_request", return_value=_resp(201, {"id": "X1"})) as req:
        out = c.create("/v1/contacts", {"name": "ACME"})
    assert out == {"id": "X1"}
    req.assert_called_once_with("POST", "v1/contacts", json={"name": "ACME"})


def test_api_error_raises_uolclienterror_with_code():
    c = _client()
    err_body = {"error": {"code": "0002", "message": "auth failed"}}
    with mock.patch.object(c, "_request", return_value=_resp(401, err_body)):
        with pytest.raises(UolClientError) as ei:
            c.create("/v1/contacts", {"name": "ACME"})
    assert ei.value.code == "0002"
    assert ei.value.status == 401


def test_is_conflict_true_for_422_status():
    # DEMO-confirmed: duplicate returns HTTP 422 with errors[].code = "has already been taken"
    c = _client()
    err = UolClientError(code="has already been taken", message="Validation failed", status=422)
    assert c.is_conflict(err) is True


def test_is_conflict_true_for_conflict_code_without_status():
    c = _client()
    err = UolClientError(code="has already been taken", message="dup", status=None)
    assert c.is_conflict(err) is True


def test_lookup_by_key_returns_slug_from_meta_href():
    # DEMO-confirmed: list response uses "items", id is slug from _meta.href
    c = _client()
    body = {
        "items": [{"_meta": {"href": "https://example.com/v1/contacts/my_slug"}, "external_id": "EXT-1"}],
        "_meta": {},
    }
    with mock.patch.object(c, "_request", return_value=_resp(200, body)):
        found = c.lookup_by_key("/v1/contacts", "external_id", "EXT-1")
    assert found == "my_slug"


def test_lookup_by_key_returns_none_when_empty():
    c = _client()
    with mock.patch.object(c, "_request", return_value=_resp(200, {"items": []})):
        assert c.lookup_by_key("/v1/contacts", "external_id", "nope") is None


def test_extract_id_returns_slug_from_meta_href():
    body = {"_meta": {"href": "https://test.demo.uol.cz/api/v1/contacts/acme-sro"}}
    assert UolClient.extract_id(body) == "acme-sro"


def test_extract_id_returns_empty_when_meta_missing():
    assert UolClient.extract_id({}) == ""


def test_extract_id_returns_empty_when_href_missing():
    assert UolClient.extract_id({"_meta": {}}) == ""


def test_parse_error_rails_style_validation():
    # DEMO-confirmed: 422 body shape
    c = _client()
    err_body = {
        "message": "Validation failed",
        "errors": [{"resource": "Contact", "field": "external_id", "code": "has already been taken"}],
    }
    with mock.patch.object(c, "_request", return_value=_resp(422, err_body)):
        with pytest.raises(UolClientError) as ei:
            c.create("/v1/contacts", {"name": "ACME"})
    assert ei.value.code == "has already been taken"
    assert ei.value.status == 422


def test_transport_error_becomes_uolclienterror_with_connection_error_code():
    c = _client()
    with mock.patch.object(c._http, "_request_raw", side_effect=requests.exceptions.ConnectionError("refused")):
        with pytest.raises(UolClientError) as ei:
            c.ping()
    assert ei.value.code == "connection_error"
    assert ei.value.status is None
    assert "Could not reach UOL API" in ei.value.message


def test_parse_error_flat_auth_failure():
    # UOL 401 uses a flat root-level shape: {"status":"401","code":"0002","message":"..."}
    c = _client()
    err_body = {"status": "401", "code": "0002", "message": "Authentication failed"}
    with mock.patch.object(c, "_request", return_value=_resp(401, err_body)):
        with pytest.raises(UolClientError) as ei:
            c.create("/v1/contacts", {"name": "ACME"})
    assert ei.value.code == "0002"
    assert ei.value.status == 401
