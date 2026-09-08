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

## 5. The extractor truncates institutional party names — T4 (observed: `brief-003`; fixed 2026-09-08)

**What happens:** *Texas Department of Community Affairs v. Burdine* was extracted with the written name "Affairs v. Burdine": the local citation parser kept only the last word of a long institutional plaintiff when the caption followed a connector like "Finally,". The name comparison still passed because the defendant carried the match, but on a shorter caption this would have produced a false NAME_MISMATCH, which is the failure that gets a checker switched off.
**Seen in the wild:** observed in our run on 2026-09-05, doc `brief-003`; the same class of parser quirk was recorded in the July build notes for "In re" captions.
**The control:** C3 kept it safe (the name threshold errs low, so a mangled caption escalates rather than being called a fabrication). The fix, shipped 2026-09-08 with a regression test: when eyecite's plaintiff is a truncated tail of the capitalised run immediately before the last "v." in the preceding text, the harness rebuilds the caption from that run. Accepted only when the rebuilt name contains everything eyecite found, so it cannot invent a longer name.

## 6. Parallel citations with a pin cite between them are counted twice — T6 (observed: `recap-479971053`; fixed 2026-09-08)

**What happens:** "536 U.S. 101, 122 S.Ct. 2061, 2072–73, 153 L.Ed.2d 106 (2002)" is one case cited three ways. The parallel detector linked the first two and treated the third as a separate citation because the pin cite "2072–73" broke adjacency. The third resolved fine, so the report showed the same case twice and inflated the totals; on an unresolved parallel it would have raised two alarms for one problem.
**Seen in the wild:** observed on the first real brief we ran, `recap-479971053` (W.D.N.C.), the second citation in the document.
**The control:** C4. Real briefs in the golden set surface parser behaviour that synthetic briefs never do. Fixed by allowing a short gap made only of digits and punctuation between parallels, with a regression test; the eval now also scores extra citations the parser produces, so a repeat would lower the extraction score.

## 7. "Ambiguous" was being read as "absent" — T6 (observed: `recap-422386605`, 20 citations; fixed 2026-09-08)

**What happens:** The lookup endpoint answers status 300 when several records share one citation: a cert-denial page in the U.S. Reports, a reporter page carrying two short opinions, a duplicate ingest. The first version of the runner treated anything other than 200 as "not found", so twenty real Fourth and Seventh Circuit cases in one environmental brief were reported UNRESOLVED. Every one of them exists.
**Seen in the wild:** observed on 2026-09-08 in `recap-422386605`; *Highway J Citizens Group v. Mineta*, 349 F.3d 938, and *Hughes River Watershed Conservancy v. Glickman*, 81 F.3d 437, among others.
**The control:** C3 kept the damage to false alarms (UNRESOLVED escalates to a person; it never says "fabricated"), and C4 caught it: real briefs in the golden set produced a miss rate the synthetic set never could. Fixed: 300 is now "exists, several records", the name check compares the written caption against every record and keeps the best match, and the resolution records how many records shared the citation.

## 8. The free database is a shared resource with a quota — T5 operational (observed 2026-09-08)

**What happens:** Thirty real briefs contain roughly six hundred citations. CourtListener's lookup endpoint rate-limited a new account after about a hundred lookups in an hour, with retry-after windows of 40 to 50 minutes, and the anonymous search path was cut off for a day after a few hundred requests. A tool that sleeps silently through those windows looks hung; a tool that retries harder gets the account banned.
**Seen in the wild:** our own runs, 2026-09-08, three separate stops.
**The control:** C2 and the egress log. The runner now stops loudly on any retry-after over ninety seconds, writes what it has, records the stop in `run.json`, and exits with a distinct code; every resolved lookup is cached so a re-run resumes at full speed. In a firm this is the argument for a paid citator behind the same interface, and for never pointing a demo at a non-profit's API on a partner's behalf without reading the terms.

## 9. A wrong pin page is invisible to a name check — T4, caught (observed: `recap-377506294`)

**What happens:** A brief cited *Sorrell v. IMS Health Inc.* at 564 U.S. 522. The case is at 564 U.S. 552. Page 522 of that volume is *Freeman v. United States*, so the citation resolved and the name did not match. This is the realistic error in a real filing: a transposed digit that lands on a different real case.
**Seen in the wild:** observed on 2026-09-08 in `recap-377506294` (E.D. Wis.). Recorded here as a catch, not a failure, because it is exactly what NAME_MISMATCH exists for, and because the tool cannot say whether it is a typo or something worse. The filing attorney can.
**The control:** C1 (the name comparison is the second layer; existence alone would have passed this) and C5 (the verdict escalates, it does not judge).

## What this agent must never be trusted to do

It must never be read as clearing a brief for filing. RESOLVED means a reporter citation exists and the name matches the database, nothing more. UNRESOLVED is not proof of fabrication. It does not read the opinion, does not check the quotation, does not check the proposition, and does not know whether the case has been overruled. The filing attorney owns every one of those, and the court will hold them to it.
