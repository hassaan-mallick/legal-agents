"""legal-agents harness.

The one rule: no quote, no claim. Every control in governance/controls-library.md
is a code path in this package, not a checklist item. Agents are plain files;
the model is chosen at runtime and never named inside an agent folder.
"""

__version__ = "0.1.0"

#: The literal an agent.yaml must use for `model`. Anything else fails validate (V03).
MODEL_SENTINEL = "provider_chosen_at_runtime"
