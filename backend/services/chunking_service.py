from dataclasses import dataclass

import tiktoken

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
ENCODING_NAME = "cl100k_base"


@dataclass(frozen=True)
class TextChunk:
    index: int
    content: str
    token_count: int
    start_token: int
    end_token: int


def count_tokens(text: str) -> int:
    return len(tiktoken.get_encoding(ENCODING_NAME).encode(text))


def normalize_text(text: str) -> str:
    cleaned = " ".join(text.split())
    return cleaned.strip()


def chunk_text_with_metadata(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Token-window chunking with overlap for retrieval-friendly context."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be zero or greater and smaller than chunk_size")

    cleaned = normalize_text(text)
    if not cleaned:
        return []

    encoding = tiktoken.get_encoding(ENCODING_NAME)
    tokens = encoding.encode(cleaned)
    chunks: list[TextChunk] = []
    start = 0

    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        token_slice = tokens[start:end]
        content = encoding.decode(token_slice).strip()
        if content:
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    content=content,
                    token_count=len(token_slice),
                    start_token=start,
                    end_token=end,
                )
            )

        if end >= len(tokens):
            break
        start = end - overlap

    return chunks


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    return [chunk.content for chunk in chunk_text_with_metadata(text, chunk_size, overlap)]
