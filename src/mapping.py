"""Pure helpers for column→field mapping. No I/O, no Keboola objects."""


def normalize(name: str) -> str:
    """Lowercase and strip separators, for fuzzy comparison."""
    return name.replace("_", "").replace("-", "").replace(" ", "").replace(".", "").lower()


def fuzzy_match(value: str, candidates: list[str]) -> str:
    """Return the best matching candidate for value, or '' if none.

    Priority: exact → case-insensitive → normalized (strip _,-,space,. + lowercase).
    """
    if value in candidates:
        return value
    value_lower = value.lower()
    for candidate in candidates:
        if candidate.lower() == value_lower:
            return candidate
    value_norm = normalize(value)
    for candidate in candidates:
        if normalize(candidate) == value_norm:
            return candidate
    return ""


def build_column_mapping_prefill(
    columns: list[str],
    fields: list[str],
    existing: list[dict],
) -> list[dict]:
    """Build a {source, destination} list for every input column.

    Existing user-set destinations are preserved verbatim; only blank/new
    columns get a fuzzy-matched destination.
    """
    existing_by_source = {
        m.get("source"): m.get("destination", "") for m in existing if isinstance(m, dict) and m.get("source")
    }
    result: list[dict] = []
    for col in columns:
        if col in existing_by_source and existing_by_source[col]:
            destination = existing_by_source[col]
        else:
            destination = fuzzy_match(col, fields)
        result.append({"source": col, "destination": destination})
    return result
