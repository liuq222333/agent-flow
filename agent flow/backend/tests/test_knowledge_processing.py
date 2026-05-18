import pytest

from app.services.knowledge_processing import (
    DocumentProcessingError,
    chunk_text,
    embed_texts,
    extract_text_from_file,
    local_hash_embedding,
    rank_chunks,
)


def test_extract_text_from_txt_markdown_json_and_csv(tmp_path) -> None:
    text_path = tmp_path / "notes.txt"
    text_path.write_text("alpha beta", encoding="utf-8")
    md_path = tmp_path / "doc.md"
    md_path.write_text(
        "# Heading\n\nmarkdown **content** with [link](https://example.com)\n\n- list item",
        encoding="utf-8",
    )
    json_path = tmp_path / "data.json"
    json_path.write_text(
        '{"title": "Refund Policy", "tags": ["billing", "support"]}',
        encoding="utf-8",
    )
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text("name,status\nOrder,shipped\n", encoding="utf-8")

    assert extract_text_from_file(text_path) == "alpha beta"
    markdown_text = extract_text_from_file(md_path)
    assert "Heading" in markdown_text
    assert "markdown content with link" in markdown_text
    assert "list item" in markdown_text
    assert "**" not in markdown_text
    assert "title: Refund Policy" in extract_text_from_file(json_path)
    assert "billing" in extract_text_from_file(json_path)
    assert "name | status" in extract_text_from_file(csv_path)
    assert "Order | shipped" in extract_text_from_file(csv_path)


def test_extract_text_from_empty_txt_returns_empty_text(tmp_path) -> None:
    text_path = tmp_path / "empty.txt"
    text_path.write_text("", encoding="utf-8")

    assert extract_text_from_file(text_path) == ""


def test_extract_text_from_unsupported_file_fails(tmp_path) -> None:
    binary_path = tmp_path / "image.png"
    binary_path.write_bytes(b"\x89PNG")

    with pytest.raises(DocumentProcessingError) as exc_info:
        extract_text_from_file(binary_path)

    assert exc_info.value.stage == "parse"
    assert "unsupported document format" in exc_info.value.message


def test_extract_text_from_binary_txt_fails_with_decode_error(tmp_path) -> None:
    binary_path = tmp_path / "broken.txt"
    binary_path.write_bytes(b"\xff\xfe\x00\x00")

    with pytest.raises(DocumentProcessingError) as exc_info:
        extract_text_from_file(binary_path)

    assert exc_info.value.stage == "parse"
    assert "failed to decode plain text as UTF-8 text" in exc_info.value.message


def test_extract_text_from_docx_when_dependency_available(tmp_path) -> None:
    docx = pytest.importorskip("docx")
    docx_path = tmp_path / "sample.docx"
    document = docx.Document()
    document.add_paragraph("DOCX paragraph text")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "left"
    table.cell(0, 1).text = "right"
    document.save(docx_path)

    extracted = extract_text_from_file(docx_path)

    assert "DOCX paragraph text" in extracted
    assert "left | right" in extracted


def test_extract_text_from_pdf_when_dependency_available(tmp_path) -> None:
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    pdf_path = tmp_path / "sample.pdf"
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 200 Td (PDF extractable text) Tj ET")
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    with pdf_path.open("wb") as file:
        writer.write(file)

    assert "PDF extractable text" in extract_text_from_file(pdf_path)


def test_chunk_text_preserves_overlap_and_uses_boundaries() -> None:
    chunks = chunk_text("alpha beta gamma delta epsilon", chunk_size=18, overlap=5)

    assert chunks == ["alpha beta gamma", "gamma delta", "delta epsilon"]


def test_chunk_text_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError):
        chunk_text("content", chunk_size=10, overlap=10)


def test_rank_chunks_scores_and_sorts_matches() -> None:
    chunks = [
        {"id": 1, "content": "billing support refund"},
        {"id": 2, "content": "billing only"},
        {"id": 3, "content": "shipping status"},
    ]

    ranked = rank_chunks(chunks, "billing refund")

    assert [item["id"] for item in ranked] == [1, 2, 3]
    assert ranked[0]["score"] == 1.0
    assert ranked[1]["score"] == 0.5


def test_local_hash_embedding_is_deterministic_and_normalized() -> None:
    first = local_hash_embedding("billing refund support", dimension=16)
    second = local_hash_embedding("billing refund support", dimension=16)

    assert first == second
    assert len(first) == 16
    assert round(sum(value * value for value in first), 6) == 1.0


@pytest.mark.asyncio
async def test_embed_texts_uses_local_provider_without_network() -> None:
    embeddings = await embed_texts(
        None,
        {"embedding_model": "local-hash", "embedding_dim": 16, "config_json": {}},
        ["billing refund", "shipping status"],
    )

    assert len(embeddings) == 2
    assert all(len(embedding) == 16 for embedding in embeddings)
