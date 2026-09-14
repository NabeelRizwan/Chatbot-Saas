"""Reject error/interstitial web responses before creating knowledge."""
import re


def validate_page_content(text: str, metadata: dict | None = None) -> None:
    metadata = metadata or {}
    status = metadata.get("statusCode") or metadata.get("status_code")
    if status is not None:
        try:
            failed_status = int(status) >= 400
        except (ValueError, TypeError):
            failed_status = True
        if failed_status:
            raise ValueError("Crawl returned an unsuccessful HTTP status.")
    if not text or not text.strip():
        raise ValueError("Crawl returned no usable content.")
    # Only response identity/lead, never later discussions of blocked accounts.
    leads = [str(metadata.get("title") or "").strip()]
    leads.extend(line.strip(" #[]*\t") for line in text[:700].splitlines()[:6] if line.strip())
    error = re.compile(
        r"^(?:(?:access denied|forbidden|request blocked|you (?:have been|are) blocked)(?:[.!:]|$)|"
        r"(?:[\w-]+\.)+[a-z]{2,}(?: is)? blocked(?:[.!:]|$)|"
        r"(?:error\s*)?(?:403|404|429|500|502|503)(?:\s*[-:–]\s*|\s+|$)|"
        r"page not found|service unavailable|internal server error|"
        r"verify (?:that )?you are human|checking your browser|"
        r"just a moment[.!…]*$|attention required!?$|captcha(?: verification)?$)", re.I,
    )
    if any(error.search(line) for line in leads):
        raise ValueError("Crawl returned a blocked, error, or verification page.")
