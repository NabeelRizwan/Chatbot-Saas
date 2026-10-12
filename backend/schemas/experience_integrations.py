import re
from typing import Literal
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from schemas.experience_urls import public_https_parts


def public_destination(value: str) -> str:
    """Validate a browser destination. This URL is never fetched by the API."""
    value = value.strip()
    if not value:
        return ""
    parsed, host = public_https_parts(value)
    if parsed.fragment:
        raise ValueError("Use a page address without a fragment")
    sensitive = {"token", "accesstoken", "key", "apikey", "password", "secret", "signature", "email", "orderid", "order", "authorization", "auth", "phone"}
    if any(re.sub(r"[^a-z0-9]", "", key.casefold()) in sensitive for key, _ in parse_qsl(parsed.query)):
        raise ValueError("Use a public entry page, not a private customer or order link")
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


class LinkAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    url: str = Field(default="", max_length=2048)
    label: str = Field(default="", max_length=60)

    _safe_destination = field_validator("url")(public_destination)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value):
        value = " ".join(value.split())
        if "<" in value or ">" in value:
            raise ValueError("Use plain text for the button label")
        return value

    @model_validator(mode="after")
    def configured_when_enabled(self):
        if self.enabled and (not self.url or self.provider == "none"):
            raise ValueError("Choose a provider and enter its page address before enabling this action")
        return self


class BookingAction(LinkAction):
    provider: Literal["none", "calcom", "calendly", "custom"] = "none"
    label: str = Field(default="Book an appointment", max_length=60)

    @model_validator(mode="after")
    def provider_destination(self):
        if self.url and self.provider in {"calcom", "calendly"}:
            domain = {"calcom": "cal.com", "calendly": "calendly.com"}[self.provider]
            host = urlsplit(self.url).hostname or ""
            if host != domain and not host.endswith("." + domain):
                raise ValueError(f"Use a {domain} address or select Custom")
        return self


class OrderAction(LinkAction):
    provider: Literal["none", "shopify", "custom"] = "none"
    label: str = Field(default="Track an order", max_length=60)


class ExperienceIntegrations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    booking: BookingAction = Field(default_factory=BookingAction)
    orders: OrderAction = Field(default_factory=OrderAction)
