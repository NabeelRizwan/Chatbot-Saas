import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from schemas.experience_urls import public_https_parts


def safe_public_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    public_https_parts(value)
    return value


class ExperienceSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    enabled: bool = False
    suggested_questions: list[str] = Field(default_factory=list, max_length=8)
    hosted_chat_enabled: bool = False
    lead_form_enabled: bool = False
    approved_faq_enabled: bool = False
    product_cards_enabled: bool = False
    font_family: Literal["system", "inter", "serif"] = "system"
    density: Literal["comfortable", "compact"] = "comfortable"
    theme: Literal["light", "dark", "auto"] = "light"
    corner_style: Literal["rounded", "soft", "square"] = "rounded"
    lead_consent_text: str = Field(default="I agree to be contacted about my request.", min_length=10, max_length=500)

    @field_validator("suggested_questions")
    @classmethod
    def questions(cls, values):
        cleaned = [s.strip() for s in values]
        if any(not s or len(s) > 200 for s in cleaned):
            raise ValueError("Suggested questions must have 1–200 characters")
        return list(dict.fromkeys(cleaned))


class FaqInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=3, max_length=1000)
    answer: str = Field(min_length=1, max_length=10000)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    source_document_id: int | None = Field(default=None, gt=0)
    source_url: str | None = None
    approved: bool = False
    enabled: bool = False

    _url = field_validator("source_url")(safe_public_url)

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, values):
        if any(not v.strip() or len(v) > 1000 for v in values):
            raise ValueError("Aliases must have 1–1000 characters")
        return list(dict.fromkeys(v.strip() for v in values))


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    url: str
    image_url: str | None = None
    price_amount: str | None = None
    currency: str = "USD"
    source_document_id: int | None = Field(default=None, gt=0)
    enabled: bool = False

    _urls = field_validator("url", "image_url")(safe_public_url)

    @field_validator("url")
    @classmethod
    def require_url(cls, value):
        if not value:
            raise ValueError("Product URL is required")
        return value

    @field_validator("price_amount")
    @classmethod
    def price(cls, value):
        if value is None or value == "":
            return None
        try:
            number = Decimal(value)
            if not number.is_finite() or number < 0 or number > 999999999 or number.as_tuple().exponent < -4:
                raise ValueError("Invalid price")
        except (InvalidOperation, ValueError):
            raise ValueError("Price must be a nonnegative decimal with up to four decimal places")
        return format(number, "f")

    @field_validator("currency")
    @classmethod
    def currency_code(cls, value):
        value = value.upper()
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("Use a three-letter currency code")
        return value


class LeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    session_id: str = Field(min_length=1, max_length=128)
    session_token: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=150)
    email: str = Field(min_length=3, max_length=254)
    phone: str | None = Field(default=None, max_length=50)
    message: str = Field(default="", max_length=3000)
    consent: Literal[True]

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class LeadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["new", "contacted", "closed"]


class ProductTurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    session_token: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=128)


class TestCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=3, max_length=4000)
    expected_answer: str = Field(default="", max_length=10000)
    required_phrases: list[str] = Field(default_factory=list, max_length=30)
    forbidden_phrases: list[str] = Field(default_factory=list, max_length=30)
    enabled: bool = True

    @field_validator("required_phrases", "forbidden_phrases")
    @classmethod
    def phrases(cls, values):
        if any(not v.strip() or len(v) > 500 for v in values):
            raise ValueError("Checks must have 1–500 characters")
        return list(dict.fromkeys(v.strip() for v in values))


class TestRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_ids: list[int] = Field(min_length=1, max_length=30)

    @field_validator("case_ids")
    @classmethod
    def case_identifiers(cls, values):
        if any(v <= 0 for v in values) or len(set(values)) != len(values):
            raise ValueError("Choose distinct saved question IDs")
        return values
