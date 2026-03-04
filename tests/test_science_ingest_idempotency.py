import types
from pathlib import Path

from handlers.research import science_ingest


class _FakeStore:
    def __init__(self, exists: bool):
        self.exists = exists
        self.register_calls = 0
        self.add_chunks_calls = 0

    def book_exists(self, _file_hash: str) -> bool:
        return self.exists

    def register_book(self, **_kwargs) -> None:
        self.register_calls += 1

    def add_chunks(self, **_kwargs) -> int:
        self.add_chunks_calls += 1
        return 1


def test_discover_pdfs_only_uses_primary_workspace(tmp_path: Path):
    primary = tmp_path / "research" / "textbooks"
    primary.mkdir(parents=True)
    pdf = primary / "local.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")

    found = science_ingest._discover_pdfs(primary)
    assert found == [pdf]


def test_ingest_skips_existing_hash_without_reingest(tmp_path: Path, monkeypatch):
    folder = tmp_path / "research" / "textbooks"
    folder.mkdir(parents=True)
    pdf = folder / "book.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")

    ingested_dir = folder / "ingested"

    fake_store = _FakeStore(exists=True)
    monkeypatch.setattr(science_ingest, "TextbookFactsStore", lambda: fake_store)
    monkeypatch.setattr(science_ingest, "DEFAULT_INGESTED_MD_DIR", ingested_dir)
    monkeypatch.setattr(science_ingest, "_sha256_file", lambda _p: "abc123")

    # ensure pdfplumber is not required for this branch
    monkeypatch.setitem(__import__("sys").modules, "pdfplumber", types.SimpleNamespace(open=None))

    books_added, chunks_added = science_ingest.ingest_folder(folder)

    assert books_added == 0
    assert chunks_added == 0
    assert fake_store.register_calls == 0
    assert fake_store.add_chunks_calls == 0
    assert (ingested_dir / "book.md").exists()
