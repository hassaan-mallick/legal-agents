import random

from harness.adversarial import seed_document
from harness.runners.citations.extract import extract


def test_seeded_citations_are_extractable_and_recorded():
    text = ("The standard is settled. A dispute is genuine if a reasonable jury could find for the non-movant. "
            "Anderson v. Liberty Lobby, Inc., 477 U.S. 242 (1986). The movant bears the initial burden. "
            "Celotex Corp. v. Catrett, 477 U.S. 317 (1986). Plaintiff cannot meet that burden here. "
            "The record shows no such evidence. Summary judgment should be granted. ") * 3
    seeded, planted = seed_document(text, 5, random.Random(1))
    assert len(planted) == 5
    _, cites = extract(seeded)
    found = {c.text.replace(" ", "") for c in cites}
    for p in planted:
        assert p["citation"].replace(" ", "") in found, p
        assert p["verdict"] == "UNRESOLVED"
    # the original citations survive untouched
    assert "477U.S.242" in found and "477U.S.317" in found
