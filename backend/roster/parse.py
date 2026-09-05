"""Rules written as free text, turned into drafts an admin confirms before use.

Nothing here decides anything on its own: every statement comes back as a
``Draft`` carrying the rule it would become, the assumptions that were made to
get there, and the reason if it could not be read at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .horizon import Horizon
from .rules import REGISTRY, build as build_rule
from .schema import HARD, SOFT, Instance, Rule

UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9}
TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
         "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
            "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
            "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
            "fifteenth": 15, "sixteenth": 16, "seventeenth": 17,
            "eighteenth": 18, "nineteenth": 19, "twentieth": 20,
            "twenty-first": 21, "twenty-fifth": 25, "thirtieth": 30,
            "thirty-first": 31}

ABBREVIATIONS = {"no.": "number", "nos.": "numbers", "e.g.": "for example",
                 "i.e.": "that is", "etc.": "etc", "viz.": "namely",
                 "mr.": "mr", "mrs.": "mrs", "ms.": "ms", "dr.": "dr",
                 "smt.": "smt", "sr.": "sr", "jr.": "jr"}

CONTRACTIONS = (("can't", "cannot"), ("won't", "will not"),
                ("shan't", "shall not"), ("ain't", "is not"), ("n't", " not"))
SLASH_UNITS = {"wk": "week", "week": "week", "day": "day", "month": "month",
               "mth": "month", "shift": "shift", "duty": "duty", "head": "head",
               "person": "person", "man": "man", "hr": "hour", "hour": "hour"}


def expand_short(text: str) -> str:
    """Contractions and slashed units written out, so one set of cues reads both."""
    out = text
    for short, plain in CONTRACTIONS:
        out = out.replace(short, plain)
    out = re.sub(r"\s*/\s*(" + "|".join(SLASH_UNITS) + r")\b",
                 lambda m: " per " + SLASH_UNITS[m.group(1)], out)
    out = re.sub(r"\bp\.?\s?w\.?(?=\s|$)", "per week", out)
    return re.sub(r"\bper wk\b", "per week", out)


RATE_BEFORE = re.compile(r"\d+(?:\.\d+)?\s*(?:hours?|hrs?|shifts?|duties|duty|days?|"
                         r"nights?|weekends?|people|staff|persons?|times?)?\s*$")


def _article_to_one(match: re.Match) -> str:
    """'a day off' counts one day; '8 hours a day' is a rate, so rates are left."""
    if RATE_BEFORE.search(match.string[:match.start()]):
        return match.group(0)
    return f"1 {match.group(1)}"


def fold_numbers(text: str) -> str:
    """Number words to digits, so one set of patterns matches either form."""
    out = text
    for word, value in ORDINALS.items():
        out = re.sub(rf"\bthe {word}\b", f"the {value}th", out)
        out = re.sub(rf"\b{word} of\b", f"{value}th of", out)
    for tens, tens_value in TENS.items():
        for unit, unit_value in UNITS.items():
            out = re.sub(rf"\b{tens}[- ]{unit}\b", str(tens_value + unit_value), out)
    for word, value in {**TEENS, **TENS, **UNITS}.items():
        out = re.sub(rf"\b{word}\b", str(value), out)
    out = re.sub(r"\ba (?:single |lone )?(day|shift|duty|hour|weekend|night|break)\b",
                 _article_to_one, out)
    return out


def split_statements(line: str) -> list[str]:
    """One line may hold several statements; full stops inside dates are safe."""
    guarded = line
    for dotted, plain in ABBREVIATIONS.items():
        guarded = re.sub(re.escape(dotted), plain, guarded, flags=re.IGNORECASE)
    parts = re.split(r";|(?<=[A-Za-z)])\.(?=\s|$)", guarded)
    return [p for p in parts if p and p.strip()]


def statements(text: str) -> list[tuple[int, str]]:
    """``(line number, statement)`` for every statement in a block of text."""
    out = []
    for number, line in enumerate(text.splitlines(), start=1):
        for part in split_statements(line):
            if part.strip():
                out.append((number, part.strip()))
    return out


def label_of(statement: str) -> str:
    """The admin's own wording, kept for the rule label."""
    out = re.sub(r"^[\s\-*•·>]+", "", statement.strip())
    out = re.sub(r"^\(?\d{1,2}[.)]\s+", "", out)
    return out.rstrip(" .").strip()


def normalise(statement: str) -> str:
    """Lower case, bullets and numbering off, number words as digits."""
    s = statement.strip().lower()
    for fancy, plain in (("–", "-"), ("—", "-"), ("‘", "'"),
                         ("’", "'"), ("&", " and ")):
        s = s.replace(fancy, plain)
    s = re.sub(r"^[\s\-*•·>]+", "", s)
    s = re.sub(r"^\(?\d{1,2}[.)]\s+", "", s)
    s = expand_short(s)
    s = re.sub(r"\bno[\s-]one\b", "nobody", s)
    s = re.sub(r"\bcan\s*not\b", "cannot", s)
    s = re.sub(r"\s+", " ", s).strip()
    return fold_numbers(s)


N = r"(\d+(?:\.\d+)?)"
MOST = (r"(?:at most|at the most|no more than|not more than|maximum(?: of)?|"
        r"max(?:imum)?|up ?to|upper limit of|cap(?:ped)? (?:at|to)|"
        r"limit(?:ed)? to|no(?:t)? (?:longer|higher|greater|larger|bigger) than|"
        r"not exceed(?:ing)?)")
LEAST = (r"(?:at least|atleast|minimum(?: of)?|min(?:imum)?|no less than|"
         r"not less than|no fewer than|not fewer than|at the very least|"
         r"no(?:t)? (?:lower|smaller|shorter) than)")
EXACTLY = r"(?:exactly|precisely|strictly)"
RUN = (r"(?:in a row|in row|consecutively|at a stretch|at a time|continuously|"
       r"back[- ]to[- ]back|on the trot|running|straight|non[- ]stop|at one go|"
       r"(?:a |one |the )?runs? of|stretch(?:es)? of|spells? of|runs?|spells?|"
       r"end on end|one after (?:the other|another))")
ADJ_RUN = (r"(?:consecutive|continuous|straight|successive|unbroken|running|"
           r"back[- ]to[- ]back|at a stretch|on end)")
PER_WEEK = (r"(?:per|a|each|every|in a|in any|in one|within a|within any|over a|"
            r"during a|of the|of a|of any)\s+(?:calendar\s+|working\s+)?week")
PER_MONTH = (r"(?:per|a|each|every|in a|in the|in any|over the|during the|for the|"
             r"in one)\s+(?:calendar\s+)?"
             r"(?:month|roster(?: period| cycle)?|period|cycle|fortnight)")
ROLLING_WEEK = (r"\brolling\b|\bany 7 (?:consecutive )?days\b|"
                r"\bany period of 7 days\b|\bany 7[- ]day (?:window|period|stretch|"
                r"span|block)\b|\bany window of 7 days\b|\bwithin any 7 days\b")
DAY_WORD = r"(?:(?:working|work|duty|rostered|on)\s+)?days?"
OFF_WORD = (r"(?:days?\s+off|off\s+days?|rest\s+days?|weekly\s+offs?|"
            r"(?<!hours )(?<!hrs )offs?|holidays?|breaks?)")
PEOPLE = (r"(?:people|persons?|staff(?:\s+members?)?|employees?|workers?|"
          r"members?|hands|bodies|heads?)")
SHIFT_WORD = r"(?:shifts?|duties|duty|turns?|slots?|watch|relay)"
HOUR_WORD = r"(?:hours?|hrs?)"
COUNTED = (r"(?:hours?|hrs?|days?|shifts?|duties|duty|nights?|weekends?|offs?|"
           r"people|persons?|staff|turns?|breaks?|holidays?|leaves?|"
           r"hands|heads?)")


def num(value) -> float:
    """Whole numbers stay whole, so params read as the admin wrote them."""
    number = float(value)
    return int(number) if number.is_integer() else number


def bounded(text: str, subject: str) -> tuple[float | None, float | None] | None:
    """The floor and ceiling stated for ``subject``, or None if neither is."""
    exact = re.search(rf"{EXACTLY}\s+{N}\s+{subject}", text)
    if exact:
        return num(exact.group(1)), num(exact.group(1))
    span = (re.search(rf"between\s+{N}\s+and\s+{N}\s+{subject}", text)
            or re.search(rf"{N}\s*(?:-|to)\s*{N}\s+{subject}", text))
    if span:
        return num(span.group(1)), num(span.group(2))
    low = re.search(rf"{LEAST}\s+{N}\s+{subject}", text)
    high = re.search(rf"{MOST}\s+{N}\s+{subject}", text)
    if not low and not high:
        return None
    return (num(low.group(1)) if low else None,
            num(high.group(1)) if high else None)


def any_bound(text: str) -> tuple[float | None, float | None]:
    """The floor and ceiling of the statement when the subject is implied."""
    exact = re.search(rf"{EXACTLY}\s+{N}", text)
    if exact:
        return num(exact.group(1)), num(exact.group(1))
    low = re.search(rf"{LEAST}\s+{N}", text)
    high = re.search(rf"{MOST}\s+{N}", text)
    return (num(low.group(1)) if low else None,
            num(high.group(1)) if high else None)


def bound_for(text: str, subject: str) -> tuple[float | None, float | None] | None:
    """The bound stated for ``subject``, or the statement's own if it trails it."""
    got = bounded(text, subject)
    if got:
        return got
    if not re.search(rf"\b{subject}\b", text):
        return None
    low, high = any_bound(text)
    return None if low is None and high is None else (low, high)


PROHIBITION = re.compile(
    r"\b(?:not|never|nobody|none|cannot|can't|won't|shouldn't|mustn't|no|avoid|"
    r"prohibit\w*|banned|barred|forbidden|restrict\w*|ceiling|exceed\w*|excess|"
    r"maximum|max|cap|capped|limit\w*)\b")
CEILING_PHRASE = re.compile(r"\bin excess of\b|\bupwards of\b|\bbeyond\s+\d|"
                            r"\bnot to (?:exceed|cross|go)\b")


def forbids(norm: str) -> bool:
    """Whether the statement forbids something, which fixes which way a bound goes."""
    return bool(PROHIBITION.search(norm) or CEILING_PHRASE.search(norm))


MORE = (r"(?:more than|greater than|over|above|beyond|past|in excess of|"
        r"upwards of|exceed(?:s|ed|ing)?)")
FEWER = r"(?:less than|fewer than|lesser than|under|below|beneath|short of)"

CEILING_NOUN = r"(?:max(?:imum)?|ceiling|upper limit|limit|cap|most)"
FLOOR_NOUN = r"(?:min(?:imum)?|floor|lower limit|least)"
SEP = r"(?:\s*[:=]\s*|\s+-\s+)"
CUE_AT = (r"\b(?:cap(?:s|ped)?|limit(?:s|ed)?|restrict(?:s|ed)?|keep(?:s)?|held|"
          r"hold(?:s)?|peg(?:s|ged)?|stop(?:s|ped)?)\s+"
          r"((?:[a-z]+\s+){0,4}?)(?:at|to)\s+" + N + r"\b")

SWAP_HEADING = re.compile(rf"\b({MOST}|{LEAST})\s+((?:[a-z]+[\s/-]+){{0,4}}?"
                          rf"{COUNTED}\b[a-z\s/-]{{0,16}}?){SEP}{N}\b")
HEAD_CEILING = re.compile(rf"\b(?:upper limit|{CEILING_NOUN}){SEP}(?=\d)")
HEAD_FLOOR = re.compile(rf"\b(?:lower limit|{FLOOR_NOUN}){SEP}(?=\d)")
SPELT_PERIOD = re.compile(rf"\b(weekly|monthly|fortnightly|daily)\s+"
                          rf"({CEILING_NOUN}|{FLOOR_NOUN})\b")
PERIODS = {"weekly": "week", "monthly": "month", "fortnightly": "fortnight",
           "daily": "day"}
TAIL = rf"([a-z\s/-]{{0,20}}?)\s*(?:is|are)?\s*(?:at\s+)?(?:the\s+)?"
POSTFIX_CEILING = re.compile(rf"\b{N}\s+((?:[a-z]+[\s/-]+){{0,3}}?{COUNTED}\b)"
                             rf"{TAIL}{CEILING_NOUN}\b")
POSTFIX_FLOOR = re.compile(rf"\b{N}\s+((?:[a-z]+[\s/-]+){{0,3}}?{COUNTED}\b)"
                           rf"{TAIL}{FLOOR_NOUN}\b")
CARRIES_ON = re.compile(rf"\b(?:and|or|but|nor|then|plus|while|except|"
                        rf"{CEILING_NOUN}|{FLOOR_NOUN})\b")
POSTFIX_BARE = re.compile(rf"\b{N}\s+(?:is\s+|are\s+)?(?:at\s+)?(?:the\s+)?"
                          rf"({CEILING_NOUN}|{FLOOR_NOUN})\b(?!\s*\d)")
SPAN_SAID = re.compile(rf"\bbetween\s+{N}\b|\b{N}\s*(?:-|to)\s*{N}\b")


def _bare(m: re.Match) -> str:
    """'6 at most' says what 'at most 6' says, with the limit standing alone."""
    word = "at most" if re.fullmatch(CEILING_NOUN, m.group(2)) else "at least"
    return f"{word} {m.group(1)}"


def _postfix(word: str):
    """A trailing limit belongs to the number only if nothing sits between them."""
    def swap(m: re.Match) -> str:
        if CARRIES_ON.search(m.group(3)):
            return m.group(0)
        return f"{word} {m.group(1)} {m.group(2)} {m.group(3)}"
    return swap


def rewrite_bounds(norm: str) -> str:
    """A limit stated as a heading, a cue or a trailing noun, put in front of its
    number where the patterns look for it."""
    out = SWAP_HEADING.sub(lambda m: f"{m.group(1)} {m.group(3)} {m.group(2)}", norm)
    out = HEAD_CEILING.sub("at most ", out)
    out = HEAD_FLOOR.sub("at least ", out)
    out = SPELT_PERIOD.sub(lambda m: f"{m.group(2)} per {PERIODS[m.group(1)]}", out)
    out = re.sub(CUE_AT, lambda m: f"{m.group(1)}at most {m.group(2)}", out)
    out = POSTFIX_CEILING.sub(_postfix("at most"), out)
    out = POSTFIX_FLOOR.sub(_postfix("at least"), out)
    if not SPAN_SAID.search(out):
        out = POSTFIX_BARE.sub(_bare, out)
    return re.sub(r"\s+", " ", out).strip()


COMPARATIVES = (
    (r"\bnot\s+(?:\w+\s+){0,4}?more than\b", "at most"),
    (r"\bnot\s+(?:\w+\s+){0,4}?exceed(?:ing)?\b", "at most"),
    (r"\bnot\s+(?:\w+\s+){0,4}?(?:less|fewer) than\b", "at least"),
    (r"\bnot\s+(?:\w+\s+){0,4}?(?:below|under)\b", "at least"),
    (r"\bnever\s+(?:\w+\s+){0,3}?more than\b", "at most"),
    (r"\bnever\s+(?:\w+\s+){0,3}?(?:less|fewer) than\b", "at least"),
    (r"\bnobody\s+(?:\w+\s+){0,3}?more than\b", "at most"),
    (r"\bnobody\s+(?:\w+\s+){0,3}?(?:less|fewer) than\b", "at least"),
    (r"\bno\s+(\w+\s+(?:\w+\s+){0,3}?)more than\b", r"\1at most"),
    (r"\bnot\s+((?:\w+\s+){0,4}?)(?:longer|higher|greater|larger|bigger) than\b",
     r"\1at most"),
    (r"\bnever\s+((?:\w+\s+){0,3}?)(?:longer|higher|greater|larger|bigger) than\b",
     r"\1at most"),
    (r"\bnobody\s+((?:\w+\s+){0,3}?)(?:longer|higher|greater|larger|bigger) than\b",
     r"\1at most"),
    (r"\bno\s+(\w+\s+(?:\w+\s+){0,3}?)(?:longer|higher|greater|larger|bigger) than\b",
     r"\1at most"),
    (r"\bnot\s+((?:\w+\s+){0,4}?)(?:shorter|lower|smaller) than\b", r"\1at least"),
    (r"\bno\s+(\w+\s+(?:\w+\s+){0,3}?)(?:shorter|lower|smaller) than\b", r"\1at least"),
    (rf"\b{N}\s+or\s+(?:fewer|less|lesser|lower|below|under)\b", r"at most \1"),
    (rf"\b{N}\s+or\s+(?:more|above|over|higher|greater)\b", r"at least \1"),
)


def rewrite_comparatives(norm: str, lean: str = "") -> tuple[str, list[str]]:
    """'must not work more than 6' becomes the 'at most 6' the patterns expect."""
    notes: list[str] = []
    out = rewrite_bounds(norm)
    for pattern, plain in COMPARATIVES:
        out = re.sub(pattern, plain, out)
    banned = forbids(norm) or "ceiling" in lean.split()
    loose_more = r"(?<!no )(?<!not )\b" + MORE + r"\s+" + N
    loose_less = r"(?<!no )(?<!not )\b" + FEWER + r"\s+" + N
    if re.search(loose_more, out):
        if banned:
            out = re.sub(loose_more, r"at most \1", out)
            if "ceiling" in lean.split():
                notes.append("'more than' was read as the most allowed")
        else:
            out = re.sub(loose_more, lambda m: f"at least {num(m.group(1)) + 1:g}", out)
            notes.append("'more than' was read as a floor one higher, since the "
                         "statement forbids nothing")
    if re.search(loose_less, out):
        if banned:
            out = re.sub(loose_less, r"at least \1", out)
            if "ceiling" in lean.split():
                notes.append("'less than' was read as the least required")
        else:
            out = re.sub(loose_less, lambda m: f"at most {num(m.group(1)) - 1:g}", out)
            notes.append("'less than' was read as a ceiling one lower, since the "
                         "statement forbids nothing")
    return re.sub(r"\s+", " ", out).strip(), notes


LEAN_SUFFIX = {"week": "per week", "month": "in the month", "run": "in a row"}
LEAN_MEANS = {"week": "counted over each week",
              "month": "counted over the whole roster period",
              "run": "counted as duties falling in a row"}
LEAN_NOTE = {
    "week": "the statement did not say over what stretch, so this reading counts "
            "each week",
    "month": "the statement did not say over what stretch, so this reading counts "
             "the whole roster period",
    "run": "the statement did not say over what stretch, so this reading counts "
           "duties falling in a row",
}

SUBJECTS = (("hours", HOUR_WORD), ("days off", OFF_WORD), ("weekends", r"weekends?"),
            ("nights", r"nights?"), ("people", PEOPLE), ("days", DAY_WORD),
            ("shifts", SHIFT_WORD))
BOUND_CUE = rf"{MOST}|{LEAST}|{EXACTLY}"
WEEK_SAID = rf"{PER_WEEK}|\bweekly\b|\bweeks?\s+(?:{BOUND_CUE})"
MONTH_SAID = rf"{PER_MONTH}|\bmonthly\b|\bmonths?\s+(?:{BOUND_CUE})"


def subject_of(pattern: str) -> str:
    """What the bound in one statement counts, or '' when nothing is countable."""
    close = re.search(rf"(?:{BOUND_CUE})\s+\d+(?:\.\d+)?\s+"
                      rf"((?:[a-z]+\s+){{0,3}}?{COUNTED}(?:\s+[a-z]+){{0,2}})",
                      pattern)
    for text in ([close.group(1)] if close else []) + [pattern]:
        for name, words in SUBJECTS:
            if re.search(rf"\b{words}\b", text):
                return name
    return ""


JOINT = r"\s*,\s*(?:and\s+)?|\s+and\s+"


def borrow(head: str, tail: str) -> tuple[str, str] | None:
    """'at most 48 hours a week and 5 duties' lends its limit to the second half."""
    cue = re.search(BOUND_CUE, head)
    counts = re.search(rf"\b\d+(?:\.\d+)?\s+(?:[a-z]+\s+){{0,3}}?{COUNTED}\b", tail)
    if not cue or not counts:
        return None
    said = f"{cue.group(0)} {tail}"
    return said, rewrite_comparatives(normalise(said))[0]


def split_compound(statement: str) -> list[str]:
    """'6 days in a row and 48 hours a week' is two limits, so it is two statements."""
    for joint in re.finditer(JOINT, statement, flags=re.IGNORECASE):
        halves = [statement[:joint.start()].strip(" ,;"),
                  statement[joint.end():].strip(" ,;")]
        read = [rewrite_comparatives(normalise(half))[0] for half in halves]
        if re.search(BOUND_CUE, read[0]) and not re.search(BOUND_CUE, read[1]):
            lent = borrow(read[0], halves[1])
            if lent:
                halves[1], read[1] = lent
        if not all(re.search(BOUND_CUE, half) for half in read):
            continue
        counted = [subject_of(half) for half in read]
        if "" in counted or counted[0] == counted[1]:
            continue
        return [halves[0]] + split_compound(halves[1])
    return [statement]


HARD_CUES = (r"\bmust\b", r"\bshall\b", r"\bmandatory\b", r"\bstatutory\b",
             r"\bcompulsory\b", r"\bnever\b", r"\bstrictly\b", r"\bmay not\b",
             r"\bcannot\b", r"\bnot allowed\b", r"\bnot permitted\b",
             r"\bunder no circumstance\w*\b", r"\bin no case\b", r"\bat all times\b",
             r"\bwithout exception\b", r"\bnon[- ]negotiable\b", r"\bhas to\b",
             r"\bhave to\b", r"\bis required\b", r"\bare required\b", r"\bensure\b",
             r"\bprohibit\w*\b", r"\bforbidden\b")
SOFT_CUES = (r"\bprefer\w*\b", r"\btry\b", r"\btries\b", r"\bideal\w*\b",
             r"\bwherever possible\b", r"\bwhere possible\b", r"\bif possible\b",
             r"\bas far as possible\b", r"\bavoid\b", r"\bdesirable\b",
             r"\bnice to have\b", r"\bwould like\b", r"\brequest\w*\b",
             r"\basked for\b", r"\bwants?\b", r"\bwish\w*\b", r"\bencourag\w*\b",
             r"\bas much as possible\b", r"\btarget\b", r"\bendeavour\b",
             r"\bas a rule of thumb\b", r"\bwherever feasible\b")
WEIGHT_CUES = ((r"\b(?:top priority|highest priority|very important|critical|"
                r"crucial|utmost|paramount)\b", 5.0),
               (r"\b(?:important|priority|matters a lot|seriously)\b", 3.0),
               (r"\b(?:if convenient|minor|low priority|nice to have|"
                r"not a big deal)\b", 0.5))


WEAK_HARD_CUES = (r"\bnobody\b", r"\bno staff\b", r"\bnone of\b", r"\bin no case\b",
                  r"\bnot to be\b", r"\bdo not\b", r"\bwill not\b")


def severity_of(norm: str) -> tuple[str, str]:
    """``(severity, note)``; severity is '' when the wording does not say."""
    if any(re.search(cue, norm) for cue in HARD_CUES):
        return HARD, ""
    if re.search(r"\bshould\b", norm) and not any(
            re.search(cue, norm) for cue in SOFT_CUES):
        return SOFT, ("'should' was read as a preference rather than a hard "
                      "limit; say 'must' if it is binding")
    if any(re.search(cue, norm) for cue in SOFT_CUES):
        return SOFT, ""
    if any(re.search(cue, norm) for cue in WEAK_HARD_CUES):
        return HARD, ""
    return "", ""


def weight_of(norm: str) -> tuple[float, str]:
    """A weight from priority wording, 1.0 when the statement is silent."""
    for cue, weight in WEIGHT_CUES:
        if re.search(cue, norm):
            return weight, f"priority wording set the weight to {weight:g}"
    return 1.0, ""


TOPICS = (
    (r"\bnight", ("max_night_shifts", "max_consecutive_same_shift",
                  "shift_type_count_range")),
    (r"\bweekend|\bsaturday|\bsunday", ("max_weekends_worked", "complete_weekends")),
    (r"\bhours?\b|\bhrs?\b", ("hours_per_window", "total_hours_range",
                              "min_rest_hours")),
    (r"\brest\b|\bgap\b|\bbreak\b", ("min_rest_hours", "min_consecutive_days_off")),
    (r"\bleave\b|\babsent\b|\bunavailable\b", ("unavailable", "day_off_request")),
    (r"\boff\b|\bholiday", ("min_days_off_per_window", "day_off_request",
                            "max_consecutive_days_off")),
    (r"\brow\b|\bstretch\b|\bconsecutive\b", ("max_consecutive_working_days",
                                              "max_consecutive_same_shift")),
    (r"\bfair|\beven|\bequal|\bshare|\bspread|\bbalance", ("balance_workload",)),
    (r"\bcover|\bstaff|\bpeople|\bhead ?count|\bvacan", ("coverage",
                                                         "headcount_per_shift")),
    (r"\bweek\b", ("max_working_days_per_window", "hours_per_window",
                   "min_days_off_per_window")),
    (r"\bmonth\b|\btotal\b", ("total_shifts_range", "total_hours_range")),
)


def hints(norm: str) -> list[str]:
    """Rule types worth a look when a statement could not be read."""
    out: list[str] = []
    for cue, types in TOPICS:
        if re.search(cue, norm):
            out.extend(t for t in types if t not in out)
    return out[:3]


SHIFT_SYNONYMS = {
    "morning": ("morning", "mornings", "morn", "am", "forenoon", "day shift",
                "general shift", "early shift", "day duty"),
    "evening": ("evening", "evenings", "afternoon", "afternoons", "pm",
                "late shift", "swing shift", "noon shift"),
    "night": ("night", "nights", "nite", "overnight", "graveyard",
              "night duty", "night shift"),
}
GUESSED_SHIFTS = {"M": "morning", "E": "evening", "N": "night"}
CONTRACT_SYNONYMS = {
    "permanent": ("permanent", "regular", "confirmed", "pensionable"),
    "contract": ("contract", "contractual", "temporary", "temp", "casual",
                 "casuals", "daily wage", "daily wager", "outsourced", "adhoc",
                 "ad hoc", "on contract"),
    "probation": ("probation", "probationer", "trainee", "on probation"),
    "part_time": ("part time", "part-time", "half time", "part timer"),
}
GENERIC_NAMES = {"staff", "employee", "worker", "member", "person", "mr", "mrs",
                 "ms", "dr", "smt", "shri", "sri"}
ATTRIBUTE_WORDS = (r"wom[ae]n", r"females?", r"ladies", r"lady", r"males?", r"men",
                   r"gents", r"senior\w*", r"junior\w*", r"new joiners?",
                   r"fresher\w*", r"pregnan\w*", r"disabled", r"divyang",
                   r"differently abled", r"married", r"unmarried", r"widow\w*",
                   r"caste", r"religio\w*", r"aged? \d+", r"handicapped")


@dataclass
class Names:
    """Everything in one statement that names something in the instance."""

    shifts: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    employees: list[str] = field(default_factory=list)
    contracts: list[str] = field(default_factory=list)
    words: list[str] = field(default_factory=list)


class Vocabulary:
    """The words that name shifts, roles, staff and contracts in this instance."""

    def __init__(self, inst: Instance | None = None) -> None:
        self.inst = inst
        self.guessed = inst is None
        self.shifts: list[tuple[str, str]] = []
        self.roles: list[tuple[str, str]] = []
        self.employees: list[tuple[str, str]] = []
        self.contracts: list[tuple[str, str]] = []
        self.night_shifts: tuple[str, ...] = ()
        self.shift_ids: tuple[str, ...] = ()
        self.unknown_groups: tuple[str, ...] = ()
        self._load()

    def _load(self) -> None:
        if self.inst is None:
            for sid, family in GUESSED_SHIFTS.items():
                self.shifts += [(word, sid) for word in SHIFT_SYNONYMS[family]]
            self.night_shifts = ("N",)
            self.shift_ids = tuple(GUESSED_SHIFTS)
            return
        for shift in self.inst.shifts:
            words = {shift.id.lower(), shift.name.lower()}
            for family, synonyms in SHIFT_SYNONYMS.items():
                if any(family in word for word in words):
                    words.update(synonyms)
            if shift.counts_as_night:
                words.update(SHIFT_SYNONYMS["night"])
            self.shifts += [(word, shift.id) for word in sorted(words)]
        self.night_shifts = tuple(s.id for s in self.inst.shifts if s.counts_as_night)
        self.shift_ids = tuple(s.id for s in self.inst.shifts)
        for role in self.inst.roles:
            words = {role.id.lower(), role.name.lower()}
            self.roles += [(word, role.id) for word in sorted(words)]
        seen: dict[str, int] = {}
        for emp in self.inst.employees:
            for word in {emp.id.lower(), emp.name.lower()}:
                self.employees.append((word, emp.id))
            first = emp.name.lower().split()[0] if emp.name else ""
            if len(first) > 2 and first not in GENERIC_NAMES:
                seen[first] = seen.get(first, 0) + 1
        for emp in self.inst.employees:
            first = emp.name.lower().split()[0] if emp.name else ""
            if seen.get(first) == 1:
                self.employees.append((first, emp.id))
        for value in sorted({e.contract for e in self.inst.employees if e.contract}):
            words = {value.lower().replace("_", " ")}
            for family, synonyms in CONTRACT_SYNONYMS.items():
                if family in value.lower() or value.lower() in synonyms:
                    words.update(synonyms)
            self.contracts += [(word, value) for word in sorted(words)]
        known = {word for word, _ in self.contracts}
        self.unknown_groups = tuple(sorted(
            word for synonyms in CONTRACT_SYNONYMS.values()
            for word in synonyms if word not in known))

    FRAMES = {
        "shifts": (r"(?:shifts?|slots?|duty|duties|turn|watch|relay)\s+{w}\b|"
                   r"\b{w}\s+(?:shifts?|slots?|duty|duties|turn|watch|relay)\b"),
        "roles": (r"(?:roles?|grades?|cadres?|categor(?:y|ies)|posts?|rank)\s+{w}\b|"
                  r"\b{w}\s+(?:staff|hands?|roles?|grades?|cadres?)\b"),
        "employees": r"(?:staff|employee|worker|member|person)\s+{w}\b",
        "contracts": r"(?:staff|employee|worker|member|person)\s+{w}\b",
    }

    def _hits(self, text: str, table: list[tuple[str, str]],
              kind: str = "employees") -> list[tuple[int, str, str]]:
        out = []
        plural = "" if kind == "employees" else r"(?:s|es)?"
        for word, ident in table:
            pattern = (self.FRAMES[kind].format(w=re.escape(word)) if len(word) == 1
                       else rf"\b{re.escape(word)}{plural}\b")
            for found in re.finditer(pattern, text):
                out.append((found.start(), ident, word))
        return sorted(out)

    @staticmethod
    def _ordered(hits: list[tuple[int, str, str]]) -> list[str]:
        out: list[str] = []
        for _, ident, _ in hits:
            if ident not in out:
                out.append(ident)
        return out

    def scan(self, text: str) -> Names:
        """Every shift, role, employee and contract named in one statement."""
        found = Names()
        for table, field_name in ((self.shifts, "shifts"), (self.roles, "roles"),
                                  (self.employees, "employees"),
                                  (self.contracts, "contracts")):
            hits = self._hits(text, table, field_name)
            getattr(found, field_name).extend(self._ordered(hits))
            found.words.extend(word for _, _, word in hits)
        return found


MONTHS = {"january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
          "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7,
          "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
          "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12,
          "dec": 12}
WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1,
            "wednesday": 2, "weds": 2, "wed": 2, "thursday": 3, "thurs": 3,
            "thur": 3, "thu": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
            "sunday": 6, "sun": 6}
MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
MONTH_TOKEN = (r"(?:(?!may\s+(?:be|have|need|want|get|do|take|require|work|not|"
               r"also|only|apply)\b)(?:" + MONTH_ALT + r"))")
WEEKDAY_ALT = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
WEEKDAY_FULL = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                "Saturday", "Sunday")

DATE_PATTERNS = (
    ("range_month", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*"
                               rf"(?:-|–|—|to|till|untill?|through|thru)\s*"
                               rf"(?:the\s+)?(\d{{1,2}})"
                               rf"(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTH_TOKEN})\b")),
    ("day_list", re.compile(rf"\b((?:\d{{1,2}}(?:st|nd|rd|th)?\s*"
                            rf"(?:,\s*|\s+and\s+|\s*&\s*)(?:the\s+)?)+)"
                            rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?"
                            rf"({MONTH_TOKEN})\b")),
    ("iso", re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")),
    ("dmy", re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")),
    ("dmy", re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b")),
    ("day_month", re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?"
                             rf"({MONTH_TOKEN})\b")),
    ("month_day", re.compile(rf"\b({MONTH_TOKEN})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b")),
    ("ordinal", re.compile(r"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b")),
    ("weekday", re.compile(rf"\b({WEEKDAY_ALT})s?\b")),
)
RANGE_JOIN = re.compile(r"^\s*(?:-|–|—|to|till|untill?|up ?to|through|thru)"
                        r"\s*(?:the\s+)?$")
BETWEEN_FIRST = re.compile(r"\bbetween\s+(?:the\s+)?$", re.I)
FOR_DAYS = re.compile(rf"\bfor\s+{N}\s+(?:days?|nights?)\b")


@dataclass
class DateScan:
    """The days one statement names, with anything assumed to get there."""

    days: list[str] = field(default_factory=list)
    weekdays: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)
    problem: str = ""
    found: bool = False


def _month_day(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _pick_year(month: int, day: int, horizon: Horizon | None,
               notes: list[str]) -> date | None:
    """A date with no year: the year that puts it inside the roster period."""
    if horizon is None:
        return None
    years = (horizon.start.year, horizon.start.year + 1, horizon.start.year - 1)
    for year in years:
        candidate = _month_day(year, month, day)
        if candidate and 0 <= (candidate - horizon.start).days < horizon.num_days:
            return candidate
    guess = _month_day(horizon.start.year, month, day)
    if guess:
        notes.append(f"no year was given, so {guess.year} was assumed")
    return guess


def _weekday_span(first: int, last: int) -> list[int]:
    """Monday to Friday is all five; Saturday to Sunday is both."""
    out = [first]
    while out[-1] != last and len(out) < 7:
        out.append((out[-1] + 1) % 7)
    return out


def _no_period(what: str) -> str:
    return (f"{what} needs the roster period to be resolved; send the instance "
            f"with the text, or write the date in full as 2026-09-15")


def _resolve(kind: str, match: re.Match, horizon: Horizon | None,
             notes: list[str]) -> tuple[list[date], list[int], str]:
    """One date-shaped phrase, as real dates or as weekday numbers."""
    said = match.group(0).strip()
    if kind == "iso":
        found = _month_day(*(int(g) for g in match.groups()))
        return ([found], [], "") if found else ([], [], f"{said} is not a real date")
    if kind == "dmy":
        day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
        if year:
            value = int(year)
            found = _month_day(value + 2000 if value < 100 else value, month, day)
            return ([found], [], "") if found else ([], [], f"{said} is not a real date")
        if horizon is None:
            return [], [], _no_period(said)
        if day <= 12:
            notes.append(f"{said} was read as day/month, so day {day} of month {month}")
        found = _pick_year(month, day, horizon, notes)
        return ([found], [], "") if found else ([], [], f"{said} is not a real date")
    if kind in ("day_month", "month_day"):
        if kind == "day_month":
            day, month = int(match.group(1)), MONTHS[match.group(2)]
        else:
            day, month = int(match.group(2)), MONTHS[match.group(1)]
        if horizon is None:
            return [], [], _no_period(said)
        found = _pick_year(month, day, horizon, notes)
        return ([found], [], "") if found else ([], [], f"{said} is not a real date")
    if kind == "range_month":
        month = MONTHS[match.group(3)]
        if horizon is None:
            return [], [], _no_period(said)
        first = _pick_year(month, int(match.group(1)), horizon, notes)
        last = _pick_year(month, int(match.group(2)), horizon, notes)
        if not first or not last:
            return [], [], f"{said} is not a real date range"
        if last < first:
            return [], [], f"{said} runs backwards"
        span = [first + timedelta(days=i) for i in range((last - first).days + 1)]
        notes.append(f"{said} was read as every day from {first.isoformat()} "
                     f"to {last.isoformat()}")
        return span, [], ""
    if kind == "day_list":
        month = MONTHS[match.group(3)]
        if horizon is None:
            return [], [], _no_period(said)
        wanted = [int(one) for one in re.findall(r"\d{1,2}", match.group(1))]
        wanted.append(int(match.group(2)))
        out = []
        for day in wanted:
            found = _pick_year(month, day, horizon, notes)
            if not found:
                return [], [], f"{said} is not a real date"
            out.append(found)
        return out, [], ""
    if kind == "ordinal":
        day = int(match.group(1))
        if horizon is None:
            return [], [], _no_period(f"'{said}'")
        hits = [horizon.date_of(i) for i in range(horizon.num_days)
                if horizon.date_of(i).day == day]
        if not hits:
            return [], [], f"the roster period has no {said}"
        if len(hits) > 1:
            notes.append(f"{said} was read as {hits[0].isoformat()}, the first "
                         f"one in the period")
        return [hits[0]], [], ""
    return [], [WEEKDAYS[match.group(1)]], ""


def scan_dates(text: str, horizon: Horizon | None) -> DateScan:
    """Every day the statement names, resolved onto the roster period."""
    scan = DateScan()
    spans: list[tuple[int, int, str, re.Match]] = []
    for kind, pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            if any(match.start() < end and start < match.end()
                   for start, end, _, _ in spans):
                continue
            spans.append((match.start(), match.end(), kind, match))
    if not spans:
        return scan
    scan.found = True
    spans.sort(key=lambda item: item[0])
    scan.spans = [(start, end) for start, end, _, _ in spans]
    parts = []
    for start, end, kind, match in spans:
        days, weekdays, problem = _resolve(kind, match, horizon, scan.notes)
        if problem:
            scan.problem = problem
            return scan
        if (kind == "day_list" and len(days) == 2
                and BETWEEN_FIRST.search(text[:start])):
            first, last = days
            if last < first:
                scan.problem = (f"{first.isoformat()} to {last.isoformat()} "
                                f"runs backwards")
                return scan
            days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
            scan.notes.append(f"'between {first.day} and {last.day}' was read as every "
                              f"day from {first.isoformat()} to {last.isoformat()}")
        elif kind == "day_list":
            scan.notes.append(match.group(0).strip() + " was read as the days "
                              + ", ".join(one.isoformat() for one in days))
        parts.append((start, end, days, weekdays))

    days: list[date] = []
    weekdays: list[int] = []
    index = 0
    while index < len(parts):
        _, end, here, here_weekdays = parts[index]
        after = parts[index + 1] if index + 1 < len(parts) else None
        joined = after is not None and RANGE_JOIN.match(text[end:after[0]])
        if joined and here and after[2]:
            first, last = here[0], after[2][-1]
            if last < first:
                scan.problem = (f"{first.isoformat()} to {last.isoformat()} "
                                f"runs backwards")
                return scan
            days += [first + timedelta(days=i) for i in range((last - first).days + 1)]
            scan.notes.append(f"read as every day from {first.isoformat()} to "
                              f"{last.isoformat()}")
            index += 2
            continue
        if joined and here_weekdays and after[3]:
            span = _weekday_span(here_weekdays[0], after[3][0])
            weekdays += span
            scan.notes.append("read as " + ", ".join(WEEKDAY_FULL[w] for w in span))
            index += 2
            continue
        days += here
        weekdays += here_weekdays
        index += 1
    return _finish_dates(scan, text, days, weekdays, horizon)


def _finish_dates(scan: DateScan, text: str, days: list[date], weekdays: list[int],
                  horizon: Horizon | None) -> DateScan:
    """Stretch 'for N days', expand weekday names, and settle the day list."""
    stretch = FOR_DAYS.search(text)
    if stretch and len(days) == 1:
        length = max(1, int(float(stretch.group(1))))
        first = days[0]
        days = [first + timedelta(days=i) for i in range(length)]
        scan.notes.append(f"read as {length} days from {first.isoformat()}")
        scan.spans.append(stretch.span())
    if weekdays:
        if horizon is None:
            scan.problem = _no_period("a weekday name")
            return scan
        wanted = sorted(set(weekdays))
        names = ", ".join(WEEKDAY_FULL[w] for w in wanted)
        hits = [horizon.date_of(i) for i in range(horizon.num_days)
                if horizon.date_of(i).weekday() in wanted]
        if not hits:
            scan.problem = f"the roster period has no {names}"
            return scan
        scan.notes.append(f"expanded to every {names} in the period "
                          f"({len(hits)} days)")
        days += hits
    scan.days = sorted({d.isoformat() for d in days})
    scan.weekdays = sorted(set(weekdays))
    return scan


@dataclass
class Refusal:
    """A statement read clearly enough to know the data model cannot hold it."""

    problem: str
    suggestions: tuple[str, ...] = ()


@dataclass
class Draft:
    """One statement and the rule it would become if the admin agrees."""

    line: int
    text: str
    rule: dict | None = None
    confidence: float = 0.0
    assumptions: list[str] = field(default_factory=list)
    problem: str = ""
    suggestions: list[str] = field(default_factory=list)
    readings: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.rule is not None

    def to_dict(self) -> dict:
        return {"line": self.line, "text": self.text, "rule": self.rule,
                "confidence": self.confidence,
                "assumptions": list(self.assumptions),
                "problem": self.problem, "suggestions": list(self.suggestions),
                "readings": [dict(r) for r in self.readings]}


PERSON_NUMBER = re.compile(r"\b(?:staff|employee|worker|member|person|emp)\s*"
                           r"(?:no\.?|number|id)?\s*#?\s*\d{1,4}\b|\be\d{1,4}\b")
FREE_NUMBER = re.compile(r"(?<![\d.:/-])(\d{1,4}(?:\.\d+)?)(?![\d:/-])")


def spare_text(pattern: str, names: Names, dates: DateScan) -> str:
    """The statement with dates and names blanked, so a stray number shows."""
    out = pattern
    for start, end in sorted(dates.spans, reverse=True):
        out = out[:start] + " " * (end - start) + out[end:]
    for word in names.words:
        out = re.sub(rf"\b{re.escape(word)}\b", " ", out)
    return PERSON_NUMBER.sub(" ", out)


def stray_numbers(spare: str) -> list[float]:
    """Numbers the statement states in its own right, which a limit must respect."""
    return [num(m.group(1)) for m in FREE_NUMBER.finditer(spare)
            if num(m.group(1)) != 1]


@dataclass
class Statement:
    """Everything read off one statement before a rule type is chosen."""

    line: int
    text: str
    norm: str
    pattern: str
    label: str
    names: Names
    dates: DateScan
    severity: str = ""
    weight: float = 1.0
    scope: dict = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    prohibited: bool = False
    explicit: bool = False
    night: str = ""
    refusal: Refusal | None = None
    spare: str = ""
    numbers: list[float] = field(default_factory=list)

    @property
    def shift(self) -> str:
        return self.names.shifts[0] if self.names.shifts else ""

    @property
    def said_a_number(self) -> bool:
        """Whether a number of its own sits in the statement, dates and ids aside."""
        return bool(self.numbers)


class Parser:
    """Reads a block of policy text and proposes rules, one statement at a time."""

    MATCHERS = (
        "impossible", "rest_hours", "hours_per_week", "hours_total",
        "same_shift_run", "day_off_run", "working_day_run", "shift_sequence",
        "role_demand", "headcount", "nights", "shift_count", "days_off_per_week",
        "working_days_per_week", "duty_total", "weekends", "coverage", "balance",
        "leave", "requests", "fixed", "preference", "out_of_scope",
    )

    def __init__(self, inst: Instance | None = None) -> None:
        self.inst = inst
        self.horizon = inst.horizon if inst is not None else None
        self.vocab = Vocabulary(inst)
        self.made = 0

    def parse(self, text: str) -> list[Draft]:
        """Every statement in ``text``, in order, as drafts."""
        out: list[Draft] = []
        for line, statement in statements(text):
            parts = split_compound(statement)
            note = ("this line set two separate limits, so it was read as two rules"
                    if len(parts) > 1 else "")
            for part in parts:
                out.extend(self.one(line, part, note))
        return out

    def one(self, line: int, statement: str, note: str = "") -> list[Draft]:
        ctx, drafts = self._read(line, statement, note)
        return self._merge(ctx, line, statement, note, drafts)

    def _read(self, line: int, statement: str, note: str = "",
              lean: str = "") -> tuple[Statement, list[Draft]]:
        ctx = self.context(line, statement, lean)
        if note:
            ctx.assumptions.append(note)
        if ctx.refusal:
            return ctx, [Draft(line=line, text=ctx.label,
                               problem=ctx.refusal.problem,
                               assumptions=list(ctx.assumptions),
                               suggestions=list(ctx.refusal.suggestions))]
        for name in self.MATCHERS:
            found = getattr(self, name)(ctx)
            if isinstance(found, Refusal):
                return ctx, [Draft(line=line, text=ctx.label, problem=found.problem,
                                   assumptions=list(ctx.assumptions),
                                   suggestions=list(found.suggestions))]
            if found:
                return ctx, [self.draft(ctx, *item) for item in found]
        return ctx, [Draft(line=line, text=ctx.label,
                           assumptions=list(ctx.assumptions),
                           problem="I could not tell which rule this is",
                           suggestions=hints(ctx.norm))]

    FLOOR_READ = "was read as a floor one higher"
    CEILING_READ = "was read as a ceiling one lower"
    WINDOW_CUE = (rf"{PER_WEEK}|{PER_MONTH}|\bweekly\b|\bmonthly\b|\bfortnightly\b|"
                  rf"\bdaily\b|\bper\s+\d+\s+days?\b|\bwindow\b|"
                  rf"\b(?:weeks?|months?|fortnights?)\s+(?:{BOUND_CUE})\b|"
                  rf"(?:per|a|each|every|in a|in any|in one|within a|within any)\s+"
                  rf"(?:calendar\s+)?(?:day|shift|duty|24 hours)\b")
    RUN_CUE = rf"\b{ADJ_RUN}\b|\b{RUN}\b"
    SHIFT_HOURS = (rf"\bshifts?\b[^.]{{0,24}}?{N}\s*{HOUR_WORD}|"
                   rf"{N}\s*{HOUR_WORD}[^.]{{0,16}}?\bper shift\b")
    SHARED = 0.6
    MOST_READINGS = 3

    def _windows(self, ctx: Statement) -> list[str]:
        """The stretches a bound could be counted over, when the words name none."""
        if (re.search(self.WINDOW_CUE, ctx.pattern)
                or re.search(self.RUN_CUE, ctx.pattern)
                or ctx.dates.spans or not any_bound(ctx.pattern)):
            return []
        if re.search(self.SHIFT_HOURS, ctx.pattern):
            return []
        if re.search(rf"\b{HOUR_WORD}\b", ctx.pattern):
            return ["week", "month"]
        return ["month", "week"]

    def _leans(self, ctx: Statement, draft: Draft) -> tuple[str, list[tuple[str, str]]]:
        """The other honest readings of a statement, when it truly reads two ways."""
        said = " ".join(draft.assumptions)
        windows = self._windows(ctx)
        if self.FLOOR_READ in said or self.CEILING_READ in said:
            floor = self.FLOOR_READ in said
            base = ("the number is the least required, one higher than the number said"
                    if floor else
                    "the number is the most allowed, one lower than the number said")
            flip = ("the number is the most allowed" if floor
                    else "the number is the least required")
            if draft.ok:
                return base, [("ceiling", flip)]
            spread: list[tuple[str, str]] = []
            for window in windows:
                spread.append((window, f"{base}, {LEAN_MEANS[window]}"))
                spread.append((f"ceiling {window}", f"{flip}, {LEAN_MEANS[window]}"))
            return base, spread + [("ceiling", flip)]
        if not draft.ok:
            return "", [(window, LEAN_MEANS[window]) for window in windows]
        if windows and ctx.shift and re.search(rf"\b{MOST}\b", ctx.pattern):
            return LEAN_MEANS["month"], [("run", LEAN_MEANS["run"])]
        return "", []

    def _merge(self, ctx: Statement, line: int, statement: str, note: str,
               drafts: list[Draft]) -> list[Draft]:
        """A statement that reads two ways carries both, so the admin picks one."""
        if len(drafts) != 1:
            return drafts
        primary = drafts[0]
        means, leans = self._leans(ctx, primary)
        if not leans:
            return drafts
        readings = [self._reading(primary, means)] if primary.ok else []
        seen = {self._shape(primary.rule)} if primary.ok else set()
        spare: list[Draft] = []
        for lean, says in leans:
            if len(readings) >= self.MOST_READINGS:
                break
            _, other = self._read(line, statement, note, lean)
            if len(other) != 1 or not other[0].ok:
                continue
            shape = self._shape(other[0].rule)
            if shape in seen:
                continue
            seen.add(shape)
            spare.append(other[0])
            readings.append(self._reading(other[0], says))
        chosen = primary
        if not primary.ok:
            if not spare:
                return drafts
            chosen = spare[0]
        if len(readings) < 2:
            chosen.readings = []
            return [chosen]
        chosen.readings = readings
        chosen.confidence = min(chosen.confidence, self.SHARED)
        chosen.assumptions.append("this statement reads more than one way, so every "
                                  "reading is offered and none was chosen for you")
        return [chosen]

    @classmethod
    def _reading(cls, draft: Draft, means: str) -> dict:
        """One reading as the page shows it: what it means and the rule it would be."""
        return {"means": means or "as written", "rule": dict(draft.rule),
                "confidence": min(draft.confidence, cls.SHARED),
                "assumptions": list(draft.assumptions)}

    @staticmethod
    def _shape(rule: dict) -> str:
        """Two readings that would build the same rule are one reading."""
        return f"{rule['type']}|{sorted(rule['params'].items())}|{rule['scope']}"

    def context(self, line: int, statement: str, lean: str = "") -> Statement:
        """Read severity, scope, shifts and dates off one statement."""
        norm = normalise(statement)
        for token in lean.split():
            if token in LEAN_SUFFIX:
                norm = f"{norm} {LEAN_SUFFIX[token]}"
        pattern, notes = rewrite_comparatives(norm, lean)
        names = self.vocab.scan(norm)
        dates = scan_dates(pattern, self.horizon)
        severity, severity_note = severity_of(norm)
        weight, weight_note = weight_of(norm)
        ctx = Statement(line=line, text=statement, norm=norm, pattern=pattern,
                        label=label_of(statement), names=names, dates=dates,
                        severity=severity, weight=weight, explicit=bool(severity),
                        prohibited=bool(PROHIBITION.search(norm)))
        ctx.assumptions = list(notes) + list(dates.notes)
        for token in lean.split():
            if token in LEAN_NOTE:
                ctx.assumptions.append(LEAN_NOTE[token])
        ctx.assumptions += [note for note in (severity_note, weight_note) if note]
        ctx.spare = spare_text(pattern, names, dates)
        ctx.numbers = stray_numbers(ctx.spare)
        if self.vocab.guessed:
            ctx.assumptions.append("no instance was sent, so shift names were "
                                   "guessed as M/E/N and nothing was checked "
                                   "against the real roster period")
        ctx.night = next((s for s in names.shifts if s in self.vocab.night_shifts), "")
        ctx.scope = self._scope(names)
        ctx.refusal = self._blocked(ctx)
        return ctx

    @staticmethod
    def _scope(names: Names) -> dict:
        if names.employees:
            return {"kind": "employees", "ids": list(names.employees)}
        if names.roles:
            return {"kind": "roles", "ids": list(names.roles)}
        if names.contracts:
            return {"kind": "contracts", "ids": list(names.contracts)}
        return {}

    GROUP_CONTEXT = (r"(?:staff|employees?|workers?|members?|people|hands|persons?|"
                     r"on)\s+{word}\b|\b{word}\s+(?:staff|employees?|workers?|"
                     r"members?|people|hands)\b")
    PERSON_REF = (r"\b(?:staff|employee|worker|member|person|emp)\s*"
                  r"(?:no\.?|number|id)?\s*#?\s*\d{1,4}\b|\be\d{1,4}\b")

    def _unnamed_person(self, ctx: Statement) -> Refusal | None:
        """A staff number the roster has never heard of must not become everyone."""
        for found in re.finditer(self.PERSON_REF, ctx.norm):
            token = found.group(0).strip()
            if any(token in seen or seen in token for seen in ctx.names.words):
                continue
            if self.vocab.guessed:
                return Refusal(f"'{token}' names a person, but no roster was sent, so "
                               f"there is nobody to match; send the staff list with "
                               f"the rules")
            return Refusal(f"there is nobody called '{token}' in the staff data, so "
                           f"this rule has nobody to cover; check the staff number")
        return None

    def _blocked(self, ctx: Statement) -> Refusal | None:
        """What no rule type can hold, whatever the statement turns out to be."""
        for word in ATTRIBUTE_WORDS:
            found = re.search(rf"\b{word}\b", ctx.norm)
            if found and not any(found.group(0) in seen for seen in ctx.names.words):
                return Refusal(
                    f"there is no '{found.group(0)}' group in the staff data, so "
                    f"this cannot be scoped; a rule can cover named staff, a role, "
                    f"a contract type, or everyone")
        for word in self.vocab.unknown_groups:
            if re.search(self.GROUP_CONTEXT.format(word=re.escape(word)), ctx.norm):
                return Refusal(
                    f"there is no '{word}' group in the staff data, so this cannot "
                    f"be scoped; record it as a contract type on the staff, or name "
                    f"the people the rule covers")
        missing = self._unnamed_person(ctx)
        if missing:
            return missing
        if ctx.dates.problem:
            return Refusal(ctx.dates.problem)
        return None

    def draft(self, ctx: Statement, rtype: str, params: dict,
              notes: tuple[str, ...] = ()) -> Draft:
        """Wrap one reading of a statement as a draft rule, checked by building it."""
        cls = REGISTRY[rtype]
        severity = ctx.severity or getattr(cls, "default_severity", HARD)
        assumptions = list(ctx.assumptions) + list(notes)
        if not ctx.severity:
            assumptions.append(f"the wording did not say how binding this is, so it "
                               f"was drafted as {severity}, the usual severity for "
                               f"{rtype}")
        scope = dict(ctx.scope)
        if scope and cls.eval_kind == "coverage":
            assumptions.append(f"{rtype} counts everyone rostered on the shift, so "
                               f"the scope was dropped")
            scope = {}
        self.made += 1
        rule = {"id": f"{rtype}_{self.made}", "type": rtype, "severity": severity,
                "weight": ctx.weight, "scope": scope,
                "params": {k: v for k, v in params.items() if v is not None},
                "label": ctx.label}
        out = Draft(line=ctx.line, text=ctx.label, rule=rule, assumptions=assumptions)
        problem = self.check(rule)
        if problem:
            out.rule = None
            out.problem = problem
            out.suggestions = [rtype]
        out.confidence = confidence_of(out, ctx.explicit)
        return out

    def check(self, rule: dict) -> str:
        """Nothing comes back as a rule unless it really builds."""
        try:
            built = Rule.from_dict(rule)
        except (TypeError, ValueError, KeyError) as exc:
            return str(exc)
        if self.inst is None:
            missing = [spec["name"] for spec in REGISTRY[rule["type"]].params_spec
                       if spec.get("required", True)
                       and spec["name"] not in rule["params"]]
            return f"parameter {missing[0]!r} is missing" if missing else ""
        try:
            build_rule(built, self.inst)
        except (TypeError, ValueError, KeyError) as exc:
            return str(exc)
        return ""

    TWO_IN_A_DAY = (r"\b(?:double shifts?|split shifts?|double duty|twice a day|"
                    r"twice in (?:a|1) day|2 (?:shifts|duties|turns)\s*"
                    r"(?:in|on|a|per|each|every)\s*(?:the same |one |1 )?day|"
                    r"both shifts (?:in|on) (?:the same|1) day)\b")

    def impossible(self, ctx: Statement):
        """What the one-shift-a-day grid cannot represent at all."""
        if re.search(self.TWO_IN_A_DAY, ctx.norm):
            return Refusal("one person gets at most one shift a day in this model, "
                           "so a second shift on the same day cannot be rostered; "
                           "add a longer shift type instead")
        return None

    REST_CUE = (r"\b(?:rest|gap|breather|interval|clear hours?)\b|"
                r"\bbetween\s+(?:\d+\s+)?(?:consecutive\s+|two\s+)?"
                r"(?:shifts?|duties|duty)\b|"
                r"\bafter (?:a|the|any|1) (?:shift|duty|night)\b|"
                r"\bbefore (?:the |his |her |their )?next (?:shift|duty|turn)\b|"
                r"\b(?:return|report|come back|be back|resume)\b[^.]{0,24}?"
                r"\bwithin\s+\d|"
                r"\bwithin\s+\d+(?:\.\d+)?\s*(?:hours?|hrs?)\s+of\b")

    def rest_hours(self, ctx: Statement):
        if not re.search(self.REST_CUE, ctx.pattern):
            return None
        found = re.search(rf"{N}\s*(?:(?:clear|full|whole|complete|continuous|"
                          rf"unbroken|straight|solid)\s+)?{HOUR_WORD}", ctx.pattern)
        if not found:
            return None
        return [("min_rest_hours", {"hours": num(found.group(1))}, ())]

    def hours_per_week(self, ctx: Statement):
        if not re.search(HOUR_WORD, ctx.pattern):
            return None
        rolling = re.search(ROLLING_WEEK, ctx.pattern)
        if not rolling and not re.search(WEEK_SAID, ctx.pattern):
            return None
        got = bound_for(ctx.pattern, HOUR_WORD)
        if not got:
            return None
        low, high = got
        params = {"min_hours": low or None, "max_hours": high}
        if rolling:
            params.update({"window": "rolling", "window_days": 7})
        return [("hours_per_window", params, ())]

    def hours_total(self, ctx: Statement):
        if not re.search(HOUR_WORD, ctx.pattern):
            return None
        if not re.search(rf"{MONTH_SAID}|\bin total\b|\baltogether\b|"
                         r"\bin all\b|\bover the (?:roster|whole|period)\b",
                         ctx.pattern):
            return None
        got = bound_for(ctx.pattern, HOUR_WORD)
        if not got:
            return None
        return [("total_hours_range", {"min_hours": got[0] or None,
                                       "max_hours": got[1]}, ())]

    def same_shift_run(self, ctx: Statement):
        if not ctx.shift or not re.search(rf"{RUN}|{ADJ_RUN}", ctx.pattern):
            return None
        low, high = any_bound(ctx.pattern)
        if high is None:
            return None
        return [("max_consecutive_same_shift",
                 {"max": int(high), "shift": ctx.shift}, ())]

    def day_off_run(self, ctx: Statement):
        pairs = re.search(r"\bin pairs\b|\bin a block\b|\bin blocks\b|\btogether\b|"
                          r"\bin one go\b|\bat one go\b", ctx.pattern)
        if not pairs and not re.search(rf"{RUN}|{ADJ_RUN}", ctx.pattern):
            return None
        if not re.search(rf"\b{OFF_WORD}\b", ctx.pattern):
            return None
        low, high = any_bound(ctx.pattern)
        out = []
        if high is not None:
            out.append(("max_consecutive_days_off", {"max": int(high)}, ()))
        if low is not None:
            out.append(("min_consecutive_days_off", {"min": int(low)}, ()))
        if not out and pairs:
            plain = re.search(rf"{N}\s+{OFF_WORD}", ctx.pattern)
            if plain:
                out.append(("min_consecutive_days_off", {"min": int(num(plain.group(1)))},
                            ("a bare number was read as the least number of days off "
                             "in a row",)))
            else:
                out.append(("min_consecutive_days_off", {"min": 2},
                            ("no number was given, so days off were taken to come in "
                             "pairs",)))
        return out or None

    BREAK_AFTER = (r"\b(?:break|rest|day off|days off|off day|offs?|holiday)\b"
                   r"[^.]{0,24}?\bafter\b[^.]{0,16}?\d")

    def working_day_run(self, ctx: Statement):
        alone = re.search(r"\bisolated\b|\bstandalone\b|\bstray\b|\bone[- ]off\b|"
                          rf"\b1 (?:{DAY_WORD})\b", ctx.pattern)
        if (not re.search(rf"{RUN}|{ADJ_RUN}", ctx.pattern) and not alone
                and not re.search(self.BREAK_AFTER, ctx.pattern)):
            return None
        if not re.search(rf"\b{DAY_WORD}\b|\bstretch\b|\b{SHIFT_WORD}\b", ctx.pattern):
            return None
        if re.search(rf"\b\d+(?:\.\d+)?\s+{OFF_WORD}\b", ctx.pattern) and not re.search(
                r"\bworking days?\b|\bwork days?\b|\bduty days?\b|"
                r"\bdays? of (?:work|duty)\b", ctx.pattern):
            return None                  # the number counts days off, not days worked
        low, high = any_bound(ctx.pattern)
        out = []
        if high is not None:
            out.append(("max_consecutive_working_days", {"max": int(high)}, ()))
        if low is not None:
            out.append(("min_consecutive_working_days", {"min": int(low)}, ()))
        if not out and alone and not ctx.said_a_number:
            out.append(("min_consecutive_working_days", {"min": 2},
                        ("a lone working day was read as a run of at least 2 days",)))
        return out or None

    def shift_sequence(self, ctx: Statement):
        if len(ctx.names.shifts) < 2 or not ctx.prohibited:
            return None
        if not re.search(r"\bfollowed by\b|\bthen\b|\bbefore\b|\bprior to\b|"
                         r"\bafter\b|\bfollowing\b|\bnext day\b|\bday after\b",
                         ctx.pattern):
            return None
        first, second = ctx.names.shifts[0], ctx.names.shifts[1]
        notes = ()
        if (re.search(r"\bafter\b|\bfollowing\b", ctx.pattern)
                and not re.search(r"\bfollowed by\b", ctx.pattern)):
            first, second = second, first
            notes = (f"'after' reverses the order, so the ban drafted is {first} "
                     f"then {second} the next day",)
        return [("forbidden_shift_sequence",
                 {"from": [first], "to": [second]}, notes)]

    NIGHT_WORD = r"(?:nights?|night\s+(?:shifts?|duties|duty))"
    ON_SITE = (r"\bon (?:site|duty|the floor|shift|nights?|premises)\b|\bpresent\b|"
               r"\bavailable\b|\brostered\b|\bposted\b|\bmanning\b|"
               r"\bat (?:night|any time|all times)\b")

    def role_demand(self, ctx: Statement):
        """How many of one role a shift needs is demand, not a rule."""
        if not ctx.names.roles:
            return None
        words = [w for w, rid in self.vocab.roles if rid in ctx.names.roles]
        if not any(re.search(rf"{N}\s+(?:\w+\s+)?{re.escape(word)}\b", ctx.pattern)
                   for word in words):
            return None
        if not re.search(rf"{SHIFT_WORD}|{self.ON_SITE}", ctx.pattern):
            return None
        return Refusal("how many of one role a shift needs is demand rather than a "
                       "rule; put the number in the demand table and the coverage "
                       "rule will hold it", ("coverage", "headcount_per_shift"))

    def headcount(self, ctx: Statement):
        got = bounded(ctx.pattern, PEOPLE)
        if not got or not re.search(rf"{self.ON_SITE}|{SHIFT_WORD}", ctx.pattern):
            return None
        low, high = got
        notes = ()
        shifts = list(ctx.names.shifts)
        if not shifts:
            shifts = list(self.vocab.shift_ids)
            notes = ("no shift was named, so this was drafted once for every shift; "
                     "drop the ones that do not apply",)
        out = []
        for shift in shifts:
            params = {"shift": shift, "min": int(low or 0)}
            if high is not None:
                params["max"] = int(high)
            if ctx.dates.days:
                params["days"] = list(ctx.dates.days)
            out.append(("headcount_per_shift", params, notes))
        return out or None

    def _number_adrift(self, ctx: Statement, what: str, instead: str,
                       suggestions: tuple[str, ...] = ()) -> Refusal:
        """A number is stated but nothing says what it limits, so nothing is drafted."""
        said = " and ".join(f"{n:g}" for n in ctx.numbers)
        first = f"{ctx.numbers[0]:g}"
        return Refusal(f"the statement names {said}, and nothing here says what that "
                       f"number limits; I will not read it as {instead} while a number "
                       f"is stated, so say it as 'at most {first} {what}' or "
                       f"'at least {first} {what}'", suggestions)

    def nights(self, ctx: Statement):
        if not ctx.night:
            return None
        got = bound_for(ctx.pattern, self.NIGHT_WORD) or bound_for(ctx.pattern,
                                                                  SHIFT_WORD)
        if not got:
            return None
        low, high = got
        if low is None:
            return [("max_night_shifts", {"max": int(high)}, ())]
        params = {"shift": ctx.night, "min": int(low)}
        if high is not None:
            params["max"] = int(high)
        return [("shift_type_count_range", params, ())]

    PREF_CUE = (r"\b(?:prefer\w*|would rather|likes?|dislikes?|hates?|rather not|"
                r"not keen|happy to|willing to|keen on|comfortable with|"
                r"does not (?:want|like|enjoy))\b")

    def shift_count(self, ctx: Statement):
        if not ctx.shift:
            return None
        got = bound_for(ctx.pattern, SHIFT_WORD)
        if not got:
            if not ctx.prohibited or re.search(self.PREF_CUE, ctx.pattern):
                return None
            if not re.search(rf"{SHIFT_WORD}|{self.NIGHT_WORD}", ctx.pattern):
                return None
            if ctx.said_a_number:
                return self._number_adrift(
                    ctx, f"{ctx.shift} shifts", f"a ban on the {ctx.shift} shift",
                    ("shift_type_count_range", "max_consecutive_same_shift"))
            return [("shift_type_count_range", {"shift": ctx.shift, "max": 0},
                     (f"no number was given, so the {ctx.shift} shift was drafted as "
                      f"barred outright",))]
        low, high = got
        params = {"shift": ctx.shift}
        if low is not None:
            params["min"] = int(low)
        if high is not None:
            params["max"] = int(high)
        return [("shift_type_count_range", params, ())]

    def days_off_per_week(self, ctx: Statement):
        if not re.search(WEEK_SAID, ctx.pattern):
            return None
        if not re.search(rf"\b{OFF_WORD}\b", ctx.pattern):
            return None
        got = bound_for(ctx.pattern, OFF_WORD)
        low, high = got if got else (None, None)
        notes = ()
        if low is None and high is None:
            plain = re.search(rf"{N}\s+{OFF_WORD}", ctx.pattern)
            if plain:
                low = num(plain.group(1))
                notes = ("a bare number was read as the least number of days off",)
            elif ctx.said_a_number:
                return self._number_adrift(ctx, "days off a week",
                                           "one day off a week",
                                           ("min_days_off_per_window",))
            else:
                low = 1
                notes = ("no number was given, so one day off a week was drafted",)
        if low is None:
            return Refusal("a ceiling on days off in a week is not a rule type; a "
                           "ceiling on working days says the same thing the other "
                           "way round", ("max_working_days_per_window",))
        return [("min_days_off_per_window",
                 {"min": int(low), "window": "calendar"}, notes)]

    WORK_DAY = DAY_WORD + r"(?!\s+off)"

    WHOLE_WEEK = (r"\ball 7 days\b|\bevery day\b|\bwhole week\b|\bfull week\b|"
                  r"\bentire week\b|\ball days of the week\b|\b7 days a week\b|"
                  r"\bseven days a week\b")

    def working_days_per_week(self, ctx: Statement):
        rolling = re.search(ROLLING_WEEK, ctx.pattern)
        whole = re.search(self.WHOLE_WEEK, ctx.pattern)
        if not rolling and not whole and not re.search(WEEK_SAID, ctx.pattern):
            return None
        if ctx.prohibited and whole:
            return [("max_working_days_per_window",
                     {"max": 6, "window": "calendar"},
                     ("a ban on working the whole week was read as at most 6 working "
                      "days in a week",))]
        got = bound_for(ctx.pattern, self.WORK_DAY)
        notes: tuple[str, ...] = ()
        if not got and not ctx.shift and not re.search(
                rf"\b{self.NIGHT_WORD}\b|\bweekends?\b", ctx.pattern):
            got = bound_for(ctx.pattern, SHIFT_WORD)
            if got:
                notes = ("one duty a day in this model, so duties in a week were read "
                         "as working days in a week",)
        if not got:
            return None
        low, high = got
        if high is None:
            return Refusal("a floor on working days in a week is not a rule type; "
                           "the same intent is usually a floor on hours, or a cap on "
                           "the days off", ("hours_per_window",
                                            "min_days_off_per_window"))
        params = {"max": int(high), "window": "calendar"}
        if rolling:
            params.update({"window": "rolling", "window_days": 7})
        if low is not None:
            notes += ("a floor on working days in a week is not a rule type, so only "
                      "the ceiling was taken",)
        return [("max_working_days_per_window", params, notes)]

    def duty_total(self, ctx: Statement):
        if not re.search(rf"{MONTH_SAID}|\bin total\b|\baltogether\b|"
                         r"\bin all\b|\bover the (?:roster|whole|period)\b",
                         ctx.pattern):
            return None
        got = bound_for(ctx.pattern, SHIFT_WORD) or bound_for(ctx.pattern,
                                                              self.WORK_DAY)
        if not got:
            return None
        low, high = got
        params = {}
        if low is not None:
            params["min"] = int(low)
        if high is not None:
            params["max"] = int(high)
        return [("total_shifts_range", params, ())]

    BOTH_DAYS = (r"\b(?:whole|complete|full|entire|both days of the)\s+weekends?\b|"
                 r"\bboth weekend days\b|\bweekends? as a whole\b|"
                 r"\bweekends?\b[^.]{0,30}?\b(?:whole|in full|entirely|both days|"
                 r"not at all)\b")
    SAT_SUN = r"\bsat(?:urday)?s?\b[^.]{0,40}?\bsun(?:day)?s?\b"
    WORKED = r"\bwork\w*|\bduty\b|\bduties\b|\brostered\b|\bposted\b"
    NOT_WORKED = r"\boff\b|\bleave\b|\baway\b|\babsent\b|\bunavailab\w+|\bholiday"

    def _paired_weekend(self, ctx: Statement) -> bool:
        """'Saturday means Sunday too' said without the word weekend."""
        return bool(re.search(self.SAT_SUN, ctx.pattern) and not ctx.scope
                    and re.search(self.WORKED, ctx.pattern)
                    and not re.search(self.NOT_WORKED, ctx.pattern))

    def weekends(self, ctx: Statement):
        if "weekend" not in ctx.pattern:
            return [("complete_weekends", {}, ())] if self._paired_weekend(ctx) else None
        if re.search(self.BOTH_DAYS, ctx.pattern):
            return [("complete_weekends", {}, ())]
        low, high = bound_for(ctx.pattern, r"weekends?") or (None, None)
        if high is not None:
            return [("max_weekends_worked", {"max": int(high)}, ())]
        if ctx.prohibited and re.search(self.ON_DUTY, ctx.pattern):
            if ctx.said_a_number:
                return self._number_adrift(ctx, "weekends", "a ban on weekend duty",
                                           ("max_weekends_worked",))
            return [("max_weekends_worked", {"max": 0},
                     ("no number was given, so weekend duty was drafted as banned "
                      "outright",))]
        if low is not None:
            return Refusal("a floor on weekends worked is not a rule type; sharing "
                           "weekend duty evenly is the usual intent",
                           ("balance_workload", "max_weekends_worked"))
        return None

    POST = r"(?:duty|duties|shifts?|posts?|positions?|slots?|vacanc\w+)"
    UNFILLED = (r"\b(?:un)?(?:staffed|filled|manned|covered)\b|"
                r"\b(?:vacant|empty|blank|short|shortfall|uncovered|open)\b")

    def coverage(self, ctx: Statement):
        if re.search(rf"\b(?:every|each|all|no|any)\s+(?:\w+\s+){{0,2}}?{self.POST}\b"
                     rf"[^.]{{0,40}}?(?:{self.UNFILLED})|"
                     rf"\b(?:no|zero|nil|0)\s+(?:{self.UNFILLED})\s+(?:\w+\s+)?"
                     rf"{self.POST}\b|"
                     r"\b(?:cover|coverage|staffing|demand|requirement)\b.{0,20}?"
                     r"\b(?:met|full|complete|maintained|satisfied)\b", ctx.pattern):
            return [("coverage", {"direction": "under"}, ())]
        if re.search(r"\b(?:extra|spare|surplus|excess|surplus) (?:people|staff|"
                     r"hands|bodies|numbers)\b|\bover ?staff\w*\b|\bidle\b|"
                     r"\bmore (?:people|staff|hands) than (?:required|needed)\b",
                     ctx.norm):
            return [("coverage", {"direction": "over"}, ())]
        return None

    FAIR = (r"\b(?:fair|fairly|fairness|evenly|even out|equal|equally|equitab\w+|"
            r"shared?|sharing|spread|distribut\w+|balanc\w+|same number|"
            r"no favourit\w*|round[- ]robin)\b")

    def balance(self, ctx: Statement):
        if not re.search(self.FAIR, ctx.pattern):
            return None
        if "weekend" in ctx.pattern:
            measure = "weekends"
        elif ctx.night or "night" in ctx.pattern:
            measure = "nights"
        elif re.search(HOUR_WORD, ctx.pattern):
            measure = "hours"
        else:
            measure = "shifts"
        params = {"measure": measure}
        within = (re.search(rf"within\s+{N}", ctx.pattern)
                  or re.search(rf"{N}\s+\w+\s+of (?:each other|one another)",
                               ctx.pattern))
        if within:
            params["tolerance"] = num(within.group(1))
        return [("balance_workload", params, ())]

    WANTS = (r"\b(?:request\w*|asked for|asks for|wants?|would like|wish\w*|"
             r"applied for|prefer\w*|has put in)\b")

    ON_DUTY = (r"\b(?:work|works|working|duty|duties|roster\w*|schedul\w*|"
               r"assign\w*|post\w*|deploy\w*|deput\w*|detail\w*|allot\w*|"
               r"engag\w*|utilis\w*|utiliz\w*|giv(?:e|en|ing)|put on|"
               r"give duty)\b")

    def leave(self, ctx: Statement):
        if not ctx.dates.days or re.search(self.WANTS, ctx.pattern):
            return None
        away = re.search(r"\b(?:leave|unavailab\w+|not available|absent|away|"
                         r"off duty|out of station|cannot come|maternity|sick|"
                         r"medical|hospital|training|deputation|exam|"
                         r"court|jury)\b", ctx.pattern)
        barred = ctx.prohibited and re.search(self.ON_DUTY, ctx.pattern)
        if not away and not barred:
            return None
        params = {"days": list(ctx.dates.days)}
        if ctx.names.shifts:
            params["shifts"] = list(ctx.names.shifts)
        return [("unavailable", params, ())]

    def requests(self, ctx: Statement):
        if not re.search(self.WANTS, ctx.pattern) or not ctx.dates.days:
            return None
        shift = ctx.shift
        days = list(ctx.dates.days)
        several = () if len(days) == 1 else (
            f"the request covers {len(days)} days, so one rule was drafted per day",)
        if re.search(r"\boff\b|\bleave\b|\bnot to work\b|\brest\b|\bfree\b|"
                     r"\bexcused\b", ctx.pattern):
            if shift:
                return [("shift_off_request", {"day": day, "shift": shift}, several)
                        for day in days]
            return [("day_off_request", {"days": days}, ())]
        if not shift:
            return None
        return [("shift_request", {"day": day, "shift": shift}, several)
                for day in days]

    def fixed(self, ctx: Statement):
        if not ctx.dates.days or not ctx.shift:
            return None
        if not re.search(r"\b(?:fixed|already (?:committed|assigned|posted|given)|"
                         r"pre[- ]assigned|standing duty|must (?:do|work|take|be on)|"
                         r"has (?:been )?(?:assigned|posted|given)|is (?:posted|"
                         r"deputed|detailed)|will (?:do|work|take|be on))\b",
                         ctx.pattern):
            return None
        if ctx.scope.get("kind") != "employees":
            return Refusal("a fixed duty needs the person named; a fixed assignment "
                           "for a whole role would put every one of them on the same "
                           "shift", ("fixed_assignment", "headcount_per_shift"))
        params = {"day": ctx.dates.days[0], "shift": ctx.shift}
        if ctx.names.roles:
            params["role"] = ctx.names.roles[0]
        notes = () if len(ctx.dates.days) == 1 else (
            f"several days were named, so the first, {ctx.dates.days[0]}, was used",)
        return [("fixed_assignment", params, notes)]

    def preference(self, ctx: Statement):
        if not ctx.shift:
            return None
        if not re.search(rf"{self.PREF_CUE}|\bavoid\b", ctx.pattern):
            return None
        avoid = re.search(r"\b(?:avoid|rather not|dislikes?|hates?|not keen|"
                          r"does not (?:want|like|enjoy))\b", ctx.pattern)
        return [("shift_preference",
                 {"shift": ctx.shift,
                  "direction": "avoid" if avoid else "prefer"}, ())]

    def out_of_scope(self, ctx: Statement):
        if re.search(rf"{N}\s*{HOUR_WORD}\b.{{0,24}}?\b(?:a|per|each|in a|in one)"
                     r"\s+day\b|\bdaily\s+(?:working\s+)?hours\b|\bhours per day\b",
                     ctx.pattern) or re.search(self.SHIFT_HOURS, ctx.pattern):
            return Refusal("a daily hours limit is set by how long a shift is, since "
                           "nobody gets more than one shift a day; change the shift "
                           "length, or cap the week",
                           ("hours_per_window", "total_hours_range"))
        if re.search(r"\brotat\w+|\bshift change\b|\bcycle of shifts\b|"
                     r"\bpattern of shifts\b|\bshift pattern\b", ctx.pattern):
            return Refusal("a fixed rotation pattern is not a rule type here; the "
                           "closest controls are a cap on how long one shift may run "
                           "and a ban on a bad succession",
                           ("max_consecutive_same_shift",
                            "forbidden_shift_sequence"))
        if re.search(r"\b(?:overtime|salary|wages?|pay|paid|payment|bonus|"
                     r"allowance|incentive|compensat\w+|arrears)\b", ctx.pattern):
            return Refusal("pay is outside the roster; the engine can only control "
                           "the hours that pay is worked out from",
                           ("hours_per_window", "total_hours_range"))
        if re.search(r"\bseniority\b|\bpromot\w+|\btransfer\w*\b|\bpostings?\b|"
                     r"\bgrade pay\b|\bconfidential report\b", ctx.pattern):
            return Refusal("there is no seniority or posting history in the data "
                           "model; group the staff a rule covers into a role or a "
                           "contract type instead")
        return None


def confidence_of(draft: Draft, explicit: bool) -> float:
    """Plain wording and few assumptions score high; nothing drafted scores zero."""
    if not draft.ok:
        return 0.0
    score = (0.92 if explicit else 0.84) - 0.07 * len(draft.assumptions)
    return round(min(0.98, max(0.25, score)), 2)


def parse(text: str, inst: Instance | None = None) -> list[Draft]:
    """Every statement in ``text`` as a draft, in the order it was written."""
    return Parser(inst).parse(text)


def parse_payload(text: str, inst: Instance | None = None) -> dict:
    """The drafts as JSON: what was read, what was not, and what to confirm."""
    drafts = parse(text, inst)
    rules = [d.rule for d in drafts if d.ok]
    return {
        "drafts": [d.to_dict() for d in drafts],
        "rules": rules,
        "unparsed": [d.to_dict() for d in drafts if not d.ok],
        "counts": {
            "statements": len(drafts),
            "drafted": len(rules),
            "unparsed": len(drafts) - len(rules),
            "hard": sum(1 for r in rules if r["severity"] == HARD),
            "soft": sum(1 for r in rules if r["severity"] == SOFT),
            "checked_against_instance": inst is not None,
        },
    }
