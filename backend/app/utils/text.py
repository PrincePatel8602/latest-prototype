"""Input sanitising for free-text user input."""
import unicodedata


def clean_text(value: str, max_len: int) -> str:
    """Remove control/format characters, collapse whitespace, cap the length.

    Control characters (newlines tricks, zero-width chars, etc.) are a common way
    to smuggle odd content into logs or prompts, so we drop them up front.
    """
    kept = "".join(
        " " if ch.isspace() else ch
        for ch in value
        if ch.isspace() or not unicodedata.category(ch).startswith("C")
    )
    return " ".join(kept.split())[:max_len]
