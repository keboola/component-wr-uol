"""Pydantic configuration for wr-uol. Connection fields are flat at root level
(the platform merges root + row parameters into one dict before run)."""

from enum import StrEnum

from keboola.component.exceptions import UserException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from endpoints import ENDPOINTS


class Environment(StrEnum):
    demo = "demo"
    sandbox = "sandbox"
    production = "production"


class WriteMode(StrEnum):
    create = "create"
    upsert = "upsert"


class ColumnMapping(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: str
    destination: str = ""


class Configuration(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # --- connection (root config) ---
    environment: Environment = Environment.demo
    customer_id: str = ""
    email: str = ""
    api_token: str = Field(alias="#api_token", default="")
    debug: bool = False

    # --- row-level ---
    endpoint: str = ""
    write_mode: WriteMode = WriteMode.create
    column_mapping: list[ColumnMapping] = Field(default_factory=list)
    batch_size: int = Field(default=100, ge=1, le=250)
    write_results_table: bool = True
    fail_on_error: bool = False

    def __init__(self, **data):
        try:
            super().__init__(**data)
        except UserException:
            raise
        except ValidationError as exc:
            messages = [f"{err['loc'][0]}: {err['msg']}" for err in exc.errors()]
            raise UserException(f"Validation Error: {', '.join(messages)}")

    @model_validator(mode="after")
    def _validate_upsert_capability(self) -> Configuration:
        if self.write_mode == WriteMode.upsert and self.endpoint:
            ep = ENDPOINTS.get(self.endpoint)
            if ep is not None and ep.lookup_key is None:
                raise UserException(
                    f"Endpoint '{self.endpoint}' does not support upsert (no lookup key). "
                    f"Use write_mode 'create'."
                )
        return self

    @property
    def base_url(self) -> str:
        if self.environment == Environment.demo:
            return "https://test.demo.uol.cz/api"
        if not self.customer_id:
            raise UserException("customer_id is required for sandbox/production environments.")
        host = "sandbox.uol.cz" if self.environment == Environment.sandbox else "ucetnictvi.uol.cz"
        return f"https://{self.customer_id}.{host}/api"
