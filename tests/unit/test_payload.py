import pytest
from keboola.component.exceptions import UserException

from endpoints import get_endpoint
from payload import build_payload


def test_scalar_fields_pass_through_as_strings():
    ep = get_endpoint("contacts")
    row = {"name": "ACME", "external_id": "C-1", "ignore_me": "x"}
    mapping = [
        {"source": "name", "destination": "name"},
        {"source": "external_id", "destination": "external_id"},
        {"source": "ignore_me", "destination": ""},
    ]  # blank dest dropped
    assert build_payload(row, mapping, ep) == {"name": "ACME", "external_id": "C-1"}


def test_nested_json_column_is_parsed():
    ep = get_endpoint("contacts")
    row = {"name": "ACME", "addresses": '[{"city": "Praha"}]'}
    mapping = [{"source": "name", "destination": "name"}, {"source": "addresses", "destination": "addresses"}]
    assert build_payload(row, mapping, ep) == {
        "name": "ACME",
        "addresses": [{"city": "Praha"}],
    }


def test_empty_nested_column_becomes_empty_list():
    ep = get_endpoint("contacts")
    row = {"name": "ACME", "addresses": ""}
    mapping = [{"source": "addresses", "destination": "addresses"}]
    assert build_payload(row, mapping, ep) == {"addresses": []}


def test_bad_json_in_nested_column_raises_userexception():
    ep = get_endpoint("contacts")
    row = {"addresses": "{not json"}
    mapping = [{"source": "addresses", "destination": "addresses"}]
    with pytest.raises(UserException, match="not valid JSON"):
        build_payload(row, mapping, ep)


def test_mapping_referencing_missing_column_raises_userexception():
    ep = get_endpoint("contacts")
    row = {"name": "ACME"}
    mapping = [{"source": "does_not_exist", "destination": "external_id"}]
    with pytest.raises(UserException, match="not found in input table"):
        build_payload(row, mapping, ep)
