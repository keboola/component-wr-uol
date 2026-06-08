"""Curated registry of writable UOL endpoints.

This is the single source of truth for what wr-uol can write to. `lookup_key`
is the capability that gates upsert: an endpoint with a non-null lookup_key
(a filterable unique key) supports upsert; one without is create-only.

Field lists are hand-maintained from the UOL OpenAPI spec (https://api.uol.cz/openapi.yaml)
because UOL has no field-introspection endpoint. The lookup_key values marked
"confirm on DEMO" in the spec are a hypothesis to verify against the DEMO instance
during implementation (Task 7); if an endpoint has no usable lookup filter, set
its lookup_key to None and it becomes create-only.
"""

from dataclasses import dataclass

from keboola.component.exceptions import UserException


@dataclass(frozen=True)
class Endpoint:
    id: str
    path: str
    label: str
    fields: tuple[str, ...]
    required_fields: tuple[str, ...] = ()
    nested_fields: tuple[str, ...] = ()
    lookup_key: str | None = None

    @property
    def supports_upsert(self) -> bool:
        return self.lookup_key is not None


ENDPOINTS: dict[str, Endpoint] = {
    "contacts": Endpoint(
        id="contacts",
        path="/v1/contacts",
        label="Contacts",
        fields=(
            "name", "company_number", "tin", "vatin", "vat_payer",
            "business_entity", "external_id", "country_id", "contract_id", "addresses",
        ),
        required_fields=("name",),
        nested_fields=("addresses",),
        lookup_key="external_id",
    ),
    "sales_invoices": Endpoint(
        id="sales_invoices",
        path="/v1/sales_invoices",
        label="Sales invoices",
        fields=(
            "buyer_id", "currency_id", "bank_account_id", "status", "type",
            "text", "note", "external_id", "items",
        ),
        required_fields=("buyer_id", "items"),
        nested_fields=("items",),
        lookup_key="external_id",  # confirm on DEMO (Task 7)
    ),
    "purchase_invoices": Endpoint(
        id="purchase_invoices",
        path="/v1/purchase_invoices",
        label="Purchase invoices",
        fields=(
            "seller_id", "public_id", "payment_method", "status",
            "total_amount", "vat1_amount", "items",
        ),
        required_fields=("seller_id", "payment_method"),
        nested_fields=("items",),
        lookup_key="public_id",  # confirm on DEMO (Task 7)
    ),
    "products": Endpoint(
        id="products",
        path="/v1/products",
        label="Products",
        fields=("name", "code", "unit", "vat_rate", "price", "external_id"),
        required_fields=("name",),
        nested_fields=(),
        lookup_key="external_id",  # confirm on DEMO (Task 7)
    ),
    "contact_bank_accounts": Endpoint(
        id="contact_bank_accounts",
        path="/v1/contact_bank_accounts",
        label="Contact bank accounts",
        fields=("bank_account_id", "contact_id", "bank_code", "bank_country_id", "currency_id", "name"),
        required_fields=("contact_id",),
        nested_fields=(),
        lookup_key=None,  # create-only
    ),
}


def get_endpoint(endpoint_id: str) -> Endpoint:
    try:
        return ENDPOINTS[endpoint_id]
    except KeyError:
        known = ", ".join(sorted(ENDPOINTS))
        raise UserException(f"Unknown endpoint '{endpoint_id}'. Known endpoints: {known}.")
