import pytest
from keboola.component.exceptions import UserException

from endpoints import ENDPOINTS, Endpoint, get_endpoint


def test_contacts_is_upsert_capable():
    ep = get_endpoint("contacts")
    assert ep.path == "/v1/contacts"
    assert ep.lookup_key == "external_id"
    assert ep.supports_upsert is True


def test_contact_bank_accounts_is_create_only():
    ep = get_endpoint("contact_bank_accounts")
    assert ep.lookup_key is None
    assert ep.supports_upsert is False


def test_contacts_declares_addresses_as_nested():
    ep = get_endpoint("contacts")
    assert "addresses" in ep.nested_fields
    assert "name" in ep.required_fields


def test_unknown_endpoint_raises_userexception():
    with pytest.raises(UserException, match="Unknown endpoint"):
        get_endpoint("not_a_real_endpoint")


def test_all_registry_entries_are_endpoint_instances():
    assert ENDPOINTS
    assert all(isinstance(e, Endpoint) for e in ENDPOINTS.values())
    assert all(key == e.id for key, e in ENDPOINTS.items())
