import sys
from unittest import mock

import pytest
from keboola.component.exceptions import UserException

sys.path.insert(0, "src")
from client.uol_client import UolClientError  # noqa: E402


def _component(monkeypatch, parameters):
    import sys
    sys.path.insert(0, "src")
    import component as mod
    comp = object.__new__(mod.Component)
    cfg_obj = mock.Mock()
    cfg_obj.parameters = parameters
    cfg_obj.action = "run"  # prevent @sync_action wrapper from swallowing UserException via exit(1)
    monkeypatch.setattr(type(comp), "configuration", property(lambda self: cfg_obj), raising=False)
    return comp, cfg_obj, mod


def test_list_endpoints_returns_select_elements(monkeypatch):
    comp, cfg, mod = _component(monkeypatch, {})
    elements = comp.list_endpoints()
    values = {e.value for e in elements}
    assert "contacts" in values
    assert "contact_bank_accounts" in values



def test_test_connection_success_returns_validation_result(monkeypatch):
    comp, cfg, mod = _component(monkeypatch, {
        "environment": "demo", "email": "e@x.cz", "#api_token": "t",
    })
    fake_client = mock.Mock()
    fake_client.ping.return_value = None
    monkeypatch.setattr(mod.Component, "_build_client", staticmethod(lambda c: fake_client))
    result = comp.test_connection()
    from keboola.component.sync_actions import ValidationResult
    assert isinstance(result, ValidationResult)


def test_test_connection_failure_raises_user_exception(monkeypatch):
    comp, cfg, mod = _component(monkeypatch, {
        "environment": "demo", "email": "e@x.cz", "#api_token": "t",
    })
    fake_client = mock.Mock()
    fake_client.ping.side_effect = UolClientError(code="connection_error", message="unreachable", status=None)
    monkeypatch.setattr(mod.Component, "_build_client", staticmethod(lambda c: fake_client))
    with pytest.raises(UserException, match="Connection failed"):
        comp.test_connection()


def test_load_column_mapping_fuzzy_fills(monkeypatch):
    comp, cfg, mod = _component(monkeypatch, {"endpoint": "contacts", "column_mapping": []})
    cfg.tables_input_mapping = [mock.Mock(source="in.c-main.t1")]
    monkeypatch.setattr(comp, "_get_input_columns",
                        lambda src: ["name", "External ID"], raising=False)
    out = comp.load_column_mapping()
    assert out["type"] == "data"
    mapping = {m["source"]: m["destination"] for m in out["data"]["column_mapping"]}
    assert mapping["name"] == "name"
    assert mapping["External ID"] == "external_id"
    assert "_metadata_" in out["data"]
