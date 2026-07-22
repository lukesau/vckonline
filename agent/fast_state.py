"""Zero-copy, dict-like read view over a live Game object.

wire_state() (full JSON round trip) is ~87% of headless step time. Move
enumeration only .get()s a handful of fields, so this module exposes the Game
object itself through a lazy dict interface and the existing enumeration code
runs unchanged against it. Parity with the serialized path is asserted by
agent/validate.py across full games.
"""


def _wrap(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return ObjView(value)
    if isinstance(value, (list, tuple)):
        return ListView(value)
    if hasattr(value, "__dict__"):
        return ObjView(value)
    return value


class ObjView(dict):
    """dict.get()-compatible view over a dict OR an arbitrary object's attributes.

    Subclasses dict (with empty own storage) purely so upstream
    `isinstance(x, dict)` checks pass; all access goes through the overrides.
    Truthiness follows the wrapped object, not the (always empty) dict storage.
    """

    __slots__ = ("_o",)

    def __init__(self, obj):
        super().__init__()
        self._o = obj

    def __bool__(self):
        return bool(self._o)

    def get(self, key, default=None):
        o = self._o
        if isinstance(o, dict):
            value = o.get(key, default)
        else:
            value = getattr(o, key, default)
        return _wrap(value)

    def __getitem__(self, key):
        o = self._o
        if isinstance(o, dict):
            return _wrap(o[key])
        try:
            return _wrap(getattr(o, key))
        except AttributeError:
            raise KeyError(key)

    def __contains__(self, key):
        o = self._o
        return key in o if isinstance(o, dict) else hasattr(o, key)

    def __repr__(self):
        return f"ObjView({self._o!r})"


class ListView(list):
    """Real list (so isinstance checks pass) that wraps elements lazily."""

    def __init__(self, items):
        super().__init__(items)

    def __getitem__(self, index):
        value = super().__getitem__(index)
        if isinstance(index, slice):
            return ListView(value)
        return _wrap(value)

    def __iter__(self):
        for value in super().__iter__():
            yield _wrap(value)


class GameView(ObjView):
    """Top-level view; patches the few wire keys that are computed, not attributes."""

    def get(self, key, default=None):
        if key == "harvest_prompt_slots":
            game = self._o
            fn = getattr(game, "harvest_slots_for_api", None)
            return _wrap(fn() if fn else [])
        return super().get(key, default)


def fast_state(game):
    return GameView(game)
