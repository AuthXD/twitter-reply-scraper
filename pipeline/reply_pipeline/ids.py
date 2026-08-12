"""Snowflake-id comparison.

Tweet ids are numeric strings, so they must be compared as numbers. Comparing
them lexicographically silently breaks resume cursors whenever two ids differ in
length ("999" sorts after "1000"), which would park a cursor in the past and
re-fetch forever.
"""


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def id_leq(a, b):
    """True if id ``a`` <= id ``b`` (numeric where possible)."""
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return na <= nb
    return str(a) <= str(b)


def max_id(ids):
    """The numerically largest id, or None for an empty/all-None iterable."""
    best = None
    for i in ids:
        if i is None:
            continue
        if best is None or not id_leq(i, best):
            best = i
    return best
