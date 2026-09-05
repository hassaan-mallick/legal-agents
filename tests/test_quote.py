from harness.document import Document, normalise, sha256_text
from harness.quote import locate, span_iou


def _doc(text: str) -> Document:
    return Document(doc_id="t", text=text, sha256=sha256_text(text))


def test_exact_match_reports_original_span():
    d = _doc("Preamble.\n\nThe term of this Agreement is two (2) years.\n")
    r = locate(d, "two (2) years")
    assert r.match == "exact"
    assert d.text[r.locator.char_start:r.locator.char_end] == "two (2) years"


def test_curly_quotes_and_line_wrap_still_exact():
    d = _doc("“Confidential Information” means any\nnon-public infor-\nmation disclosed.")
    r = locate(d, '"Confidential Information" means any non-public information disclosed.')
    assert r.match == "exact"


def test_paraphrase_is_missing():
    d = _doc("The Recipient shall keep all Confidential Information strictly confidential.")
    r = locate(d, "Recipient must keep information secret at all times and forever")
    assert r.match == "missing"


def test_short_quote_is_missing():
    d = _doc("Governing law: Delaware.")
    assert locate(d, "law").match == "missing"


def test_page_and_heading():
    d = _doc("1. DEFINITIONS\nsome text\n\fSection two text.\n3. GOVERNING LAW\nDelaware law applies here.")
    r = locate(d, "Delaware law applies here")
    assert r.locator.page == 2
    assert r.locator.heading == "3. GOVERNING LAW"


def test_normalise_offsets_round_trip():
    text = "a  b\n\nc"
    norm, offs = normalise(text)
    assert norm == "a b c"
    assert [text[i] for i in offs] == ["a", " ", "b", "\n", "c"]


def test_span_iou():
    assert span_iou((0, 10), (0, 10)) == 1.0
    assert span_iou((0, 10), (5, 15)) == 1 / 3
    assert span_iou((0, 10), (20, 30)) == 0.0
