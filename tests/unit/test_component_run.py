from unittest import mock

from client.uol_client import UolClientError


def _make_component(monkeypatch, tmp_path, params, table_rows, columns):
    """Build a Component with config + one input table, client mocked."""
    import sys
    sys.path.insert(0, "src")
    import component as component_module

    comp = object.__new__(component_module.Component)

    cfg_obj = mock.Mock()
    cfg_obj.parameters = params
    # configuration is a read-only property on ComponentBase; patch it on the instance class
    monkeypatch.setattr(type(comp), "configuration", property(lambda self: cfg_obj), raising=False)

    table = mock.Mock()
    table.full_path = str(tmp_path / "in.csv")
    table.columns = columns
    import csv
    with open(table.full_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in table_rows:
            w.writerow(r)
    comp.get_input_tables_definitions = mock.Mock(return_value=[table])

    comp.create_out_table_definition = mock.Mock(return_value=mock.Mock(full_path=str(tmp_path / "out.csv")))
    comp.write_manifest = mock.Mock()
    return comp, component_module


def test_run_create_happy_path_calls_create_per_row(monkeypatch, tmp_path):
    params = {
        "environment": "demo", "email": "e@x.cz", "#api_token": "t",
        "endpoint": "contacts", "write_mode": "create",
        "column_mapping": [{"source": "name", "destination": "name"}],
        "write_results_table": False,
    }
    comp, mod = _make_component(monkeypatch, tmp_path,
                                params, [{"name": "A"}, {"name": "B"}], ["name"])
    fake_client = mock.Mock()
    fake_client.create.return_value = {"id": "X"}
    monkeypatch.setattr(comp, "_build_client", lambda cfg: fake_client, raising=False)
    comp.run()
    assert fake_client.create.call_count == 2


def test_run_upsert_falls_back_to_lookup_then_patch_on_conflict(monkeypatch, tmp_path):
    params = {
        "environment": "demo", "email": "e@x.cz", "#api_token": "t",
        "endpoint": "contacts", "write_mode": "upsert",
        "column_mapping": [{"source": "external_id", "destination": "external_id"},
                           {"source": "name", "destination": "name"}],
        "write_results_table": False,
    }
    comp, mod = _make_component(monkeypatch, tmp_path, params,
                               [{"external_id": "E1", "name": "A"}], ["external_id", "name"])
    fake_client = mock.Mock()
    fake_client.create.side_effect = UolClientError("has already been taken", "duplicate", 422)
    fake_client.is_conflict.return_value = True
    fake_client.lookup_by_key.return_value = "C9"
    fake_client.update.return_value = {"id": "C9"}
    monkeypatch.setattr(comp, "_build_client", lambda cfg: fake_client, raising=False)
    comp.run()
    fake_client.lookup_by_key.assert_called_once()
    fake_client.update.assert_called_once()
