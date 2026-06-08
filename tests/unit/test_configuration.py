import pytest
from keboola.component.exceptions import UserException

from configuration import Configuration, Environment, WriteMode


def _base(**overrides) -> dict:
    data = {
        "environment": "demo",
        "email": "test@example.com",
        "#api_token": "secret",
        "endpoint": "contacts",
        "write_mode": "create",
        "column_mapping": [{"source": "name", "destination": "name"}],
    }
    data.update(overrides)
    return data


def test_minimal_config_parses_and_exposes_token_via_alias():
    cfg = Configuration(**_base())
    assert cfg.api_token == "secret"
    assert cfg.endpoint == "contacts"
    assert cfg.write_mode == WriteMode.create
    assert cfg.write_results_table is True  # default on
    assert cfg.batch_size == 100


def test_environment_defaults_to_production_when_omitted():
    # Safety: an omitted environment must NOT fall back to demo.
    data = {k: v for k, v in _base().items() if k != "environment"}
    cfg = Configuration(**data)
    assert cfg.environment == Environment.production


def test_demo_is_still_accepted_programmatically():
    # demo is hidden from the UI schema but must remain valid in code (for testing).
    cfg = Configuration(**_base(environment="demo"))
    assert cfg.environment == Environment.demo


def test_demo_base_url():
    cfg = Configuration(**_base())
    assert cfg.base_url == "https://test.demo.uol.cz/api"


def test_production_base_url_requires_customer_id():
    cfg = Configuration(**_base(environment="production", customer_id="acme"))
    assert cfg.base_url == "https://acme.ucetnictvi.uol.cz/api"


def test_production_without_customer_id_raises():
    cfg = Configuration(**_base(environment="production", customer_id=""))
    with pytest.raises(UserException, match="customer_id is required"):
        _ = cfg.base_url


def test_upsert_on_create_only_endpoint_raises():
    with pytest.raises(UserException, match="does not support upsert"):
        Configuration(**_base(endpoint="contact_bank_accounts", write_mode="upsert"))


def test_upsert_on_capable_endpoint_ok():
    cfg = Configuration(**_base(endpoint="contacts", write_mode="upsert"))
    assert cfg.write_mode == WriteMode.upsert


def test_batch_size_out_of_range_raises_userexception():
    with pytest.raises(UserException, match="batch_size"):
        Configuration(**_base(batch_size=9999))
