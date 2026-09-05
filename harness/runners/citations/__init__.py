"""Citation verifier runner — port of the July 2026 citation-verifier build.

No model call anywhere in this package. Extraction is local (eyecite); only
{volume, reporter, page} triples reach CourtListener through the guarded
client, and every outbound request is in the egress log.
"""
