from unittest import mock

import pytest
from keboola.component.exceptions import UserException


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


def test_list_fields_for_contacts_marks_required(monkeypatch):
    comp, cfg, mod = _component(monkeypatch, {"endpoint": "contacts"})
    fields = comp.list_fields()
    name = next(f for f in fields if f["field_name"] == "name")
    assert "(required)" in name["label"]


def test_list_fields_without_endpoint_raises(monkeypatch):
    comp, cfg, mod = _component(monkeypatch, {})
    with pytest.raises(UserException, match="Select an endpoint"):
        comp.list_fields()


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
