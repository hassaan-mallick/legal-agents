from pathlib import Path

from harness.ingest import _strip_repeated_headers, ingest
from harness.runners.citations.classify import Verdict, classify, uncheckable
from harness.runners.citations.extract import ExtractedCitation
from harness.runners.citations.resolve import Resolution


def _cite(reporter: str, volume="2022", page="11867136") -> ExtractedCitation:
    return ExtractedCitation(text=f"{volume} {reporter} {page}", volume=volume, reporter=reporter,
                             page=page, start=0, end=10, plaintiff="A", defendant="B")


def test_westlaw_and_lexis_are_not_checked_not_unresolved():
    for rep in ("WL", "U.S. Dist. LEXIS", "LEXIS"):
        assert uncheckable(_cite(rep))
        f = classify(_cite(rep), Resolution(found=False))
        assert f.verdict is Verdict.NOT_CHECKED
        assert f.needs_review and f.confidence == 0.0
    assert not uncheckable(_cite("U.S.", "477", "242"))


def test_outage_stays_separate_from_absence():
    a = classify(_cite("U.S.", "477", "242"), Resolution(found=False, unavailable=True, error="429"))
    b = classify(_cite("U.S.", "477", "242"), Resolution(found=False))
    assert a.verdict is Verdict.NOT_CHECKED and b.verdict is Verdict.UNRESOLVED


def test_repeated_headers_are_dropped_but_body_kept():
    pages = [f"Case 1:23-cv-1 Document 9\nBody text page {i}\nPage {i} of 4" for i in range(4)]
    out, dropped = _strip_repeated_headers(pages)
    assert dropped == 4
    assert all("Body text page" in p for p in out)
    assert all("Case 1:23-cv-1" not in p for p in out)


def test_ingest_txt_counts_pages(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_text("one\fTwo\fthree")
    assert ingest(p).pages == 3


def test_caption_rebuilt_from_context_after_connector():
    from harness.runners.citations.extract import extract

    _, c = extract("Finally, Texas Department of Community Affairs v. Burdine, 450 U.S. 248 (1981).")
    assert c[0].written_name == "Texas Department of Community Affairs v. Burdine"


def test_parallel_cites_with_pin_cite_between_are_one_case():
    from harness.runners.citations.extract import extract

    text = "Nat'l R.R. Passenger Corp. v. Morgan, 536 U.S. 101, 122 S.Ct. 2061, 2072–73, 153 L.Ed.2d 106 (2002)."
    _, c = extract(text)
    assert [x.parallel_to for x in c] == [None, 0, 0]
