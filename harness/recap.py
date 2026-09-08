"""Fetch public briefs from CourtListener's RECAP archive into a corpus collection.

RECAP documents are filed, public federal court records. We search for a
document type (memoranda in support of summary judgment by default), download
the PDF through the guarded client, convert to text with page breaks, and
record case name, court, docket, document id, URL and sha256 in the manifest.
Nothing here touches a model.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from harness.document import Manifest
from harness.egress import EgressLog, GuardedClient
from harness.ingest import pdf_to_text

SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"
STORAGE = "https://storage.courtlistener.com/"
ALLOW = {"www.courtlistener.com", "storage.courtlistener.com"}
USER_AGENT = "legal-agents/0.1 corpus fetch (https://github.com/hassaan-mallick/legal-agents)"
DEFAULT_QUERY = '"memorandum of law in support of motion for summary judgment"'


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48]


def fetch_briefs(collection_dir: Path, *, query: str = DEFAULT_QUERY, count: int = 30,
                 min_pages: int = 6, max_pages: int = 40, token: str | None = None,
                 seen_courts_cap: int = 4) -> list[dict]:
    """Search RECAP, download up to `count` briefs, return manifest entries added."""
    log = EgressLog(allow=set(ALLOW))
    client = GuardedClient(log, user_agent=USER_AGENT, timeout=60)
    headers = {"Authorization": f"Token {token}"} if token else {}
    manifest = Manifest(collection_dir / "manifest.json")
    pdf_dir = collection_dir / "pdf"
    doc_dir = collection_dir / "docs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)

    added: list[dict] = []
    per_court: dict[str, int] = {}
    page = 1
    cursor_url: str | None = None
    while len(added) < count and page <= 15:
        params = {"type": "r", "q": query, "available_only": "on", "order_by": "score desc"}
        url = cursor_url or SEARCH_URL
        resp, rec = client.request("GET", url, payload=params if not cursor_url else {"cursor": True},
                                   params=None if cursor_url else params, headers=headers, note="search")
        if resp is None or resp.status_code != 200:
            print(f"search stopped: {rec.note or (resp.status_code if resp else 'no response')}")
            break
        data = resp.json()
        for result in data.get("results", []):
            court = result.get("court") or "?"
            for doc in result.get("recap_documents") or []:
                if len(added) >= count:
                    break
                desc = (doc.get("short_description") or doc.get("description") or "").lower()
                if "memorandum" not in desc and "brief" not in desc:
                    continue
                pages = doc.get("page_count") or 0
                if not doc.get("is_available") or not doc.get("filepath_local"):
                    continue
                if not (min_pages <= pages <= max_pages):
                    continue
                if per_court.get(court, 0) >= seen_courts_cap:
                    continue
                doc_id = f"recap-{doc['id']}"
                if doc_id in manifest.entries:
                    continue
                pdf_url = STORAGE + doc["filepath_local"]
                r2, rec2 = client.request("GET", pdf_url, payload={"document": doc["id"]}, note="pdf")
                if r2 is None or r2.status_code != 200 or not r2.content.startswith(b"%PDF"):
                    continue
                pdf_path = pdf_dir / f"{doc_id}.pdf"
                pdf_path.write_bytes(r2.content)
                try:
                    ing = pdf_to_text(pdf_path)
                except Exception as exc:  # unreadable scan, encrypted, etc.
                    print(f"skip {doc_id}: {exc.__class__.__name__}")
                    pdf_path.unlink(missing_ok=True)
                    continue
                if len(ing.text.strip()) < 2000:
                    pdf_path.unlink(missing_ok=True)
                    continue  # scanned image PDF with no text layer
                txt_path = doc_dir / f"{doc_id}.txt"
                txt_path.write_text(ing.text)
                entry = manifest.add_file(
                    txt_path, doc_id=doc_id, source="public court filing", licence="US public record",
                    url=pdf_url, filer=result.get("caseName"), form=doc.get("short_description") or "brief",
                    filed=result.get("dateFiled"), fetched_at=dt.datetime.now(dt.UTC).isoformat(),
                    notes=(f"{court}; docket {result.get('docketNumber')}; {pages} pages; "
                           f"pdf sha256 in pdf/{doc_id}.pdf; {ing.dropped_header_lines} header lines dropped"))
                per_court[court] = per_court.get(court, 0) + 1
                added.append(entry.to_json())
                print(f"{doc_id:<18} {pages:>3}p  {court[:34]:<34} {result.get('caseName', '')[:40]}")
        cursor_url = data.get("next")
        if not cursor_url:
            break
        page += 1
    manifest.save()
    (collection_dir / "egress.jsonl").unlink(missing_ok=True)
    log.write(collection_dir / "egress.jsonl")
    return added
