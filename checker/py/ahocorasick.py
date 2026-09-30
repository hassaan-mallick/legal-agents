"""Pure-Python stand-in for pyahocorasick, for the browser build (no wasm wheel).

eyecite uses the automaton only to pre-select which extractors could match a
text, and unions every value it yields. Yielding each word found once, with
any end index, selects exactly the same extractors. Slower than the C
automaton; a brief takes well under a second.
"""

from __future__ import annotations


class Automaton:
    def __init__(self, *_args, **_kwargs):
        self._words: dict[str, object] = {}

    def add_word(self, key: str, value: object) -> bool:
        fresh = key not in self._words
        self._words[key] = value
        return fresh

    def make_automaton(self) -> None:
        pass

    def iter(self, text: str):
        for word, value in self._words.items():
            i = text.find(word)
            if i != -1:
                yield i + len(word) - 1, value
