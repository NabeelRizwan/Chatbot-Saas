from urllib.parse import urlsplit


def selected_source_metadata(sources):
    """Keep only the identifiers needed to attach catalog cards to a saved answer."""
    selected = []
    for source in (sources or [])[:32]:
        if not isinstance(source, dict):
            continue
        item = {}
        for key in ("document_id", "doc_id"):
            value = source.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                item["document_id"] = value
        url = source.get("source_url")
        if isinstance(url, str) and len(url) <= 2048:
            try:
                parsed = urlsplit(url)
                if parsed.scheme.lower() in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
                    item["source_url"] = url
            except ValueError:
                pass
        if item and item not in selected:
            selected.append(item)
    return selected
