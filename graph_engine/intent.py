"""Intent-typed edges (Roadmap V2#3, Zettelkasten lesson).

Beyond bare similarity ("similar"/"extends") the engine detects
INTENT between two nodes from signals in the text:

  supersedes      new makes old obsolete        ("API v2 replaces v1")
  contradicts     new denies/opposes old        ("The Earth is NOT flat")
  continues       new continues/builds on old   ("further ... based on")

Heuristic (no NLP dependency), deterministic and testable. Returns None
when no intent is detected — similarity then decides as before.

Audit #35/#36/#51/#61 (fix wave 3): markers match on token boundaries
("versetzt" no longer fires "ersetzt"), the subject check runs
clause-scoped (the marker must share a sentence with a shared content
word — mere presence in the text is not enough), the negation check runs
bidirectionally (new affirms what old denied -> contradicts too), and
the marker sets are fully bilingual.
"""

from __future__ import annotations

import re

# Marker sequences (lowercase). Matching is token-based: a marker only
# matches when its tokens appear as a SEQUENCE in the token stream —
# "versetzt" (tokens: [versetzt]) no longer matches "ersetzt", while
# "findet statt" (tokens [findet, statt]) still matches the supersedes
# marker "statt" because it really occurs as its own word there (but only
# in the same clause as the subject — see _clause_hits).
# Bilingual (Audit #61): every set covers DE and EN.
SUPERSEDE_MARKERS: tuple[tuple[str, ...], ...] = (
    ("ersetzt",), ("ersetzt", "durch"), ("ersatz",),
    ("ablöst",), ("löst", "ab"), ("abgelöst",),
    ("supersedes",), ("superseded",), ("replaces",), ("replaced", "by"),
    ("obsolet",), ("obsolete",), ("deprecated",),
    ("statt",), ("anstelle", "von"), ("instead", "of"), ("replaces",),
)
CONTRADICT_MARKERS: tuple[tuple[str, ...], ...] = (
    ("ist", "nicht"), ("nicht", "mehr"), ("keineswegs",),
    ("widerspricht",), ("widersprochen",),
    ("keine",), ("kein",), ("niemals",), ("nie",),
    ("ist", "falsch"), ("falsch",), ("falsche",),
    ("is", "not"), ("no", "longer"), ("never",), ("not", "true"),
    ("false",), ("wrong",), ("contradicts",),
)
CONTINUE_MARKERS: tuple[tuple[str, ...], ...] = (
    ("setzt", "fort"), ("basiert", "auf"), ("aufbauend",),
    ("weiterentwicklung",), ("weiterentwickelt",), ("verfeinert",),
    ("erweitert", "um"), ("fortgeführt",),
    ("builds", "on"), ("based", "on"), ("extends",), ("extends", "with"),
    ("continues",), ("continued",), ("refines",), ("follows", "from"),
)

# Priority on multiple hits (audit #51): supersedes > contradicts
# > continues — documented and deterministic; the clause-scoped subject
# check already disambiguates most double hits.
_PRIORITY = ("supersedes", "contradicts", "continues")

# The three intent kinds, public and single-source: the review policy
# (`review.INTENT_KINDS` import) and the eval oracle both bound their behavior
# on this tuple instead of re-listing the strings.
INTENT_KINDS: tuple[str, ...] = _PRIORITY

_MARKER_TO_INTENT: dict[tuple[str, ...], str] = {}
for _m in SUPERSEDE_MARKERS:
    _MARKER_TO_INTENT[_m] = "supersedes"
for _m in CONTRADICT_MARKERS:
    _MARKER_TO_INTENT[_m] = "contradicts"
for _m in CONTINUE_MARKERS:
    _MARKER_TO_INTENT[_m] = "continues"

_WORD_RE = re.compile(r"[a-zäöüß0-9]+")

# Common function/stop words (DE + EN) that do NOT indicate topical overlap.
# Without the filter `shared` would be almost always true (die/der/und/ist… in
# every text), which would make the intent subject check ineffective.
_STOPWORDS = frozenset(
    """
    die der das und ist ein eine einer eines mit von für auf den dem aus bei
    als wie nur auch sich nicht keine kein sind wird werden wurde sein ihre
    ihren ihrer diesem diese dieses dieser gegen über unter zwischen ohne weil
    dass durch zum zur im am in an wir ich du er sie es war hat habe haben
    dann wenn so aber oder noch nach vor hier da bitte würde können sollen
    muss worden indem obwohl deshalb trotz außer sowohl sowie bspw z.b bzw
    the and is are with for on of a an to in not no this that but or as was
    were been has have it its be been can will would should must shall may
    """.split()
)


def _tokens(text: str) -> list[str]:
    """Token stream: lowercase, punctuation separated (Audit #36: "Erde," was
    previously a different token than "Erde")."""
    return _WORD_RE.findall(text.lower())


def _content_words(text: str) -> set[str]:
    return {w for w in _tokens(text) if len(w) >= 3 and w not in _STOPWORDS}


def _clauses(text: str) -> list[list[str]]:
    """Sentence/clause boundaries: . ! ? ; , : and line breaks separate."""
    parts = re.split(r"[.!?;,:()\[\]\"\']|\n+", text.lower())
    return [_tokens(p) for p in parts if _tokens(p)]


def _marker_hits(tokens: list[str], markers: tuple[tuple[str, ...], ...]) -> list[tuple[str, ...]]:
    """Markers that occur as contiguous token sequences."""
    hits = []
    n = len(tokens)
    for m in markers:
        L = len(m)
        for i in range(n - L + 1):
            if tokens[i:i + L] == list(m):
                hits.append(m)
                break
    return hits


# Noun-negation/replacement markers: here the negated/replaced thing is the
# OBJECT of the marker — it must appear as a shared content word SHORTLY AFTER
# the marker. "keine Zeit für Review" negates "Zeit", not "Review" (Audit #35);
# "findet statt" has no object after "statt" (stattfinden verb, no supersedes).
_OBJECT_MARKERS = frozenset(("keine", "kein", "nie", "niemals", "statt", "falsch",
                             "falsche", "no", "never", "false", "wrong"))


def _marker_object_shared(clause: list[str], marker: tuple[str, ...], subjects: set[str]) -> bool:
    if marker[0] not in _OBJECT_MARKERS:
        return True  # verbal markers: subject-in-clause check suffices
    # Find the end position of the marker; a shared content word within the
    # next 2 tokens makes the negation the subject ("keine Scheibe" ✓,
    # "keine Zeit für Review" ✗ — Review sits at position +3 and is not
    # the negated thing). The window is positional (articles/adjectives in
    # between are fine).
    n = len(clause)
    for i in range(n - len(marker) + 1):
        if clause[i:i + len(marker)] == list(marker):
            window = clause[i + len(marker):i + len(marker) + 2]
            if set(window) & subjects:
                return True
    return False


def _clause_hits(clauses: list[list[str]], markers: tuple[tuple[str, ...], ...],
                 subjects: set[str]) -> bool:
    """True when a marker shares a sentence/clause with a subject content word.

    Audit #35: mere marker presence in the text fired against EVERY related
    node ("Der Mitarbeiter wird versetzt" → supersedes because of the
    'ersetzt' substring in 'versetzt' + shared domain words). Now the marker
    must be in the same sentence as a shared content word — and for object
    markers (keine/kein/nie/statt/falsch) the negated/replaced object itself
    must be shared."""
    for clause in clauses:
        if not (_content_words(" ".join(clause)) & subjects):
            continue
        hits = _marker_hits(clause, markers)
        if any(_marker_object_shared(clause, m, subjects) for m in hits):
            return True
    return False


def detect_intent(new_text: str, old_text: str) -> str | None:
    """Intent between the new and the existing node, or None.

    `new_text` is the newly ingested statement, `old_text` the existing one.
    All three intents require that both talk about the same subject
    (shared content words) AND that the marker shares a sentence with a
    shared content word (Audit #35).

    Audit #36 (bidirectional negation): if OLD denies the subject and
    NEW affirms it (or vice versa), that is also contradicts — before,
    new-affirms-what-old-denies returned None.
    """
    new_subjects = _content_words(new_text)
    shared = new_subjects & _content_words(old_text)
    if not shared:
        return None

    new_clauses = _clauses(new_text)
    old_clauses = _clauses(old_text)

    hits: dict[str, bool] = {}
    for intent, markers in (
        ("supersedes", SUPERSEDE_MARKERS),
        ("contradicts", CONTRADICT_MARKERS),
        ("continues", CONTINUE_MARKERS),
    ):
        hits[intent] = (
            _clause_hits(new_clauses, markers, shared)
            or _clause_hits(old_clauses, markers, shared)
        )

    # Bidirectional negation (Audit #36): old denies, new affirms the same
    # subject without negation → contradiction between the statements.
    if not hits["contradicts"]:
        old_denies = _clause_hits(old_clauses, CONTRADICT_MARKERS, shared)
        new_denies = _clause_hits(new_clauses, CONTRADICT_MARKERS, shared)
        if old_denies and not new_denies:
            hits["contradicts"] = True

    for intent in _PRIORITY:
        if hits[intent]:
            return intent
    return None
