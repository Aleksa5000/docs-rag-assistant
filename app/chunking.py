import re


def chunk_text(text: str, size: int = 90, overlap: int = 25) -> list[str]:
    """Split text into word-based windows of `size` words that share `overlap` words."""
    if size <= overlap:
        raise ValueError("size must be greater than overlap")
    words = text.split()
    if not words:
        return []
    chunks, step = [], size - overlap
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start : start + size]))
        if start + size >= len(words):
            break
    return chunks


_STOP = set(
    "a an and are as at be by can do does for from how i in is it of on or our the "
    "to was we what when where which who why will with you your my me".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", text.lower()) if t not in _STOP]
