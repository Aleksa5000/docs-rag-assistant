import pytest

from app import config, ingest, store
from app.chunking import chunk_text, tokenize


def test_chunking_overlap_and_coverage():
    words = [f"w{i}" for i in range(250)]
    chunks = chunk_text(" ".join(words), size=100, overlap=20)
    assert len(chunks) == 3
    assert chunks[0].split()[-20:] == chunks[1].split()[:20]  # overlap is shared
    assert chunks[-1].split()[-1] == "w249"  # nothing dropped at the end


def test_chunking_edge_cases():
    assert chunk_text("   ") == []
    assert chunk_text("one two three", size=10, overlap=2) == ["one two three"]
    with pytest.raises(ValueError):
        chunk_text("x", size=5, overlap=5)


def test_tokenize_drops_stopwords():
    assert tokenize("What is the Refund policy?") == ["refund", "policy"]


def seed():
    store.init_db()
    store.add_document("handbook.md", None, [(None, "Vacation: employees receive 25 days of paid vacation."),
                                             (None, "Sick leave is 10 days per year.")])
    store.add_document("faq.pdf", None, [(3, "The battery lasts 14 days on a single charge."),
                                         (4, "Wi-Fi works on 2.4 GHz only.")])


def test_retrieval_ranks_relevant_chunk_first():
    seed()
    hits = store.search("how many vacation days do employees get")
    assert hits[0]["filename"] == "handbook.md" and "vacation" in hits[0]["text"]
    hits = store.search("battery charge")
    assert (hits[0]["filename"], hits[0]["page"]) == ("faq.pdf", 3)


def test_retrieval_returns_nothing_for_unrelated_query():
    seed()
    assert store.search("quantum chromodynamics") == []
    assert store.search("the of and") == []  # only stopwords


def test_retrieval_respects_k(monkeypatch):
    seed()
    assert len(store.search("days", k=2)) == 2
    monkeypatch.setenv("TOP_K", "0")  # a zero/negative TOP_K must not silently answer "not found"
    assert config.top_k() == 1 and len(store.search("days")) == 1


def test_delete_cascades_chunks():
    seed()
    doc = store.list_documents()[0]
    assert store.delete_document(doc["id"]) == ""
    assert store.delete_document(doc["id"]) is None
    assert all(h["doc_id"] != doc["id"] for h in store.search("days"))


@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd.txt", "passwd.txt"),
    ("C:\\Users\\bob\\report.pdf", "report.pdf"),
    ("we ird<>name?.md", "we ird__name_.md"),
    ("Quarterly_Board_Report_" + "x" * 110 + ".pdf", "Quarterly_Board_Report_" + "x" * 93 + ".pdf"),
    ("a" * 300 + ".notes.txt", "a" * 116 + ".txt"),
])
def test_safe_filename(raw, expected):
    assert ingest.safe_filename(raw) == expected


def test_validate_rules():
    assert ingest.validate("a.TXT", b"hi", 100) == "a.TXT"
    with pytest.raises(ingest.UploadError, match="the 0.5 MB limit"):
        ingest.validate("a.txt", b"x" * (512 * 1024 + 1), 512 * 1024)
    for name, data, status in [("a.exe", b"x", 415), ("a.txt", b"", 400), ("a.txt", b"x" * 101, 413),
                               ("a.pdf", b"not a pdf", 400)]:
        with pytest.raises(ingest.UploadError) as e:
            ingest.validate(name, data, 100)
        assert e.value.status == status
