"""Fuzzy search scoring — pure Python, no GTK. Shared by app and window search."""

def score(query: str, *fields: str) -> float:
    """Score how well `query` matches any of `fields`. Higher is better, 0 = no match.

    Scoring: exact-prefix on the name field wins, then word-prefix, then
    substring, then ordered-subsequence (fuzzy). Earlier fields weigh more.
    """
    q = query.strip().lower()
    if not q:
        return 0.0
    best = 0.0
    for weight, field in enumerate(fields):
        f = (field or "").lower()
        if not f:
            continue
        field_weight = 1.0 / (weight + 1)
        if f == q:
            s = 100.0
        elif f.startswith(q):
            s = 80.0 + (len(q) / max(len(f), 1)) * 10.0
        else:
            # word-prefix: query matches the start of any word
            words = f.replace("-", " ").replace("_", " ").split()
            if any(w.startswith(q) for w in words):
                s = 60.0 + (len(q) / max(len(f), 1)) * 10.0
            elif q in f:
                s = 40.0 + (len(q) / max(len(f), 1)) * 10.0
            else:
                # fuzzy: ordered subsequence with gap penalty
                s = _fuzzy(q, f)
                if s <= 0:
                    continue
        best = max(best, s * field_weight)
    return best


def _fuzzy(q: str, f: str) -> float:
    """Ordered-subsequence match. Returns 0..30, 0 when not all chars found in order."""
    qi, gaps, consec, best_consec = 0, 0, 0, 0
    for ch in f:
        if qi < len(q) and ch == q[qi]:
            qi += 1
            consec += 1
            best_consec = max(best_consec, consec)
        else:
            if qi > 0:
                gaps += 1
            consec = 0
    if qi < len(q):
        return 0.0
    # reward consecutive runs, penalize gaps and long fields
    return max(1.0, 25.0 * (best_consec / len(q)) - gaps * 1.5 - len(f) * 0.05)


def ranked(query: str, items, key):
    """Return items sorted by score desc. `key(item)` -> tuple of fields."""
    scored = []
    for it in items:
        s = score(query, *key(it))
        if s > 0:
            scored.append((s, it))
    scored.sort(key=lambda p: -p[0])
    return [it for _, it in scored]
