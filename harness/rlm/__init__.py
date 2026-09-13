"""Recursive-language-model runtime for matter folders (prototype).

A root RLM receives the matter's documents as variables inside a sandboxed
interpreter (Deno + Pyodide, no network, no filesystem) and writes small
programs to search, slice and read them, calling sub-models on the parts
that matter. It is the workflow runtime: the existing agents become modules
it can dispatch.

Governance carried over from the harness:
- the interpreter has no network and no filesystem outside the variables it
  was given; the only way out is the model call, which is logged;
- every quoted passage in the answer is located in the source by the same
  quote locator the agents use; a quote that cannot be located is reported
  as such, never silently kept;
- no output is final; the result is a review item for a named person.
"""
