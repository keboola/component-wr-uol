from mapping import build_column_mapping_prefill, fuzzy_match, normalize


def test_normalize_strips_separators_and_lowercases():
    assert normalize("External_ID") == "externalid"
    assert normalize("company-number") == "companynumber"
    assert normalize("Bank Account.ID") == "bankaccountid"


def test_fuzzy_match_exact_wins():
    assert fuzzy_match("name", ["name", "Name"]) == "name"


def test_fuzzy_match_case_insensitive():
    assert fuzzy_match("Name", ["name", "external_id"]) == "name"


def test_fuzzy_match_normalized():
    assert fuzzy_match("External ID", ["external_id", "name"]) == "external_id"


def test_fuzzy_match_no_match_returns_empty():
    assert fuzzy_match("totally_unrelated", ["name", "external_id"]) == ""


def test_prefill_preserves_existing_and_fills_blanks():
    columns = ["name", "External ID", "weird_col"]
    fields = ["name", "external_id", "country_id"]
    existing = [{"source": "name", "destination": "country_id"}]  # user override kept
    result = build_column_mapping_prefill(columns, fields, existing)
    assert result == [
        {"source": "name", "destination": "country_id"},   # preserved, not re-matched
        {"source": "External ID", "destination": "external_id"},  # fuzzy filled
        {"source": "weird_col", "destination": ""},          # no match → blank
    ]
