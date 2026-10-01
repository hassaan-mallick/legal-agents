"""Stand-in for fast_diff_match_patch (no wasm wheel). eyecite imports it for
annotate_citations(), which the checker never calls."""


def diff(*_args, **_kwargs):
    raise RuntimeError("fast_diff_match_patch is not available in the browser build")
