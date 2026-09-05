# How this agent fails

The section nobody else publishes. Each mode is mapped to the atlas taxonomy and the control that catches it. Two of the four were observed in our own runs; the doc ids are in the golden set.

## 1. A typo is indistinguishable from a fabrication — T6 (observed: `brief-003`, `brief-006`, every third brief)

**What happens:** *Reeves v. Sanderson Plumbing Products, Inc.* is a real case at 530 U.S. 133. Written as 530 U.S. 331, it comes back UNRESOLVED, exactly like the wholly invented *Whitmore v. Cascade Logistics* in the same brief. Nothing in the output distinguishes a lawyer's transposed digits from a chatbot's invention.
**Seen in the wild:** this is the honest ceiling of existence checking, and the reason *Mata v. Avianca* style checks are review queues, not verdicts. Presenting UNRESOLVED as "fake" would be a T6 failure by the tool itself.
**The control:** C5 and C2. The verdict enum has no "fabricated"; UNRESOLVED escalates to the filing attorney with the explanation that the database's coverage is thinner for unpublished opinions, recent decisions and state trial courts. The golden set plants this case on purpose and scores it UNRESOLVED so the ceiling is measured, not hidden.

## 2. An outage wearing the costume of a finding — T6

**What happens:** The anonymous CourtListener search endpoint refuses roughly every other request with HTTP 429 at 1.2-second spacing. The first version of this tool (July 2026) caught the exception and returned "not found", so it announced that *Bush v. Gore* and *McDonnell Douglas* did not exist.
**Seen in the wild:** observed during the original build on 2026-07-26 (recorded in the July build notes); the eval now runs offline from a cache precisely so a rate limit cannot become a result.
**The control:** C3. `Resolution.unavailable` is a separate field from `found`, surfaces as NOT_CHECKED with confidence 0, and is never written to the cache. C4: the offline eval refuses to score an unavailable lookup as anything but NOT_CHECKED.

## 3. Real citation, invented name — T1 (observed: every brief in the golden set)

**What happens:** *Harrington v. Vance Capital Partners*, 550 U.S. 544 resolves cleanly. The citation is real; it belongs to *Bell Atlantic Corp. v. Twombly*. An existence-only checker, which is what most people build in an afternoon, reports it as fine.
**Seen in the wild:** the pattern in *Mata v. Avianca* and *Park v. Kim* was not gibberish citations but plausible names attached to real-looking numbers.
**The control:** C1 in two layers. The citation text as written is the quote and is located in the source; the written case name is compared against the resolved name with a measured threshold (token_set_ratio 60, chosen from the empty gap between genuine matches at 76–100 and genuine mismatches at 20–38). NAME_MISMATCH escalates.

## 4. Existence is not support — T2

**What happens:** Every citation in a brief is RESOLVED and correctly named, and the brief still cites *Anderson v. Liberty Lobby* for a proposition it does not stand for. This agent cannot see that.
**Seen in the wild:** T2 is the most common failure in the atlas after fabrication, and no existence checker touches it.
**The control:** C2 and C5. The human gate is the filing attorney before the table of authorities is finalised; the verdict is RESOLVED, never "verified", and the document disposition is `needs_review` at best. Proposition checking is flagship F5's problem, not this agent's.

## 5. The extractor truncates institutional party names — T4 (observed: `brief-003`)

**What happens:** *Texas Department of Community Affairs v. Burdine* is extracted with the written name "Affairs v. Burdine": the local citation parser keeps only the last word of a long institutional plaintiff. The name comparison still passed (the defendant carries the match), but on a shorter caption this would produce a false NAME_MISMATCH, which is the failure that gets a checker switched off.
**Seen in the wild:** observed in our run on 2026-09-05, doc `brief-003`; the same class of parser quirk was recorded in the July build notes for "In re" captions.
**The control:** C3. The name threshold errs low (60) precisely so a legitimately shortened or mangled caption escalates as NAME_MISMATCH for a human rather than being reported as a fabrication; the explanation text tells the reviewer both names. The fix belongs in extraction (use the preceding-text window as a fallback name), and it is tracked here until it is measured.

## What this agent must never be trusted to do

It must never be read as clearing a brief for filing. RESOLVED means a reporter citation exists and the name matches the database, nothing more. UNRESOLVED is not proof of fabrication. It does not read the opinion, does not check the quotation, does not check the proposition, and does not know whether the case has been overruled. The filing attorney owns every one of those, and the court will hold them to it.
