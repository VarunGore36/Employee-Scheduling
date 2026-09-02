# Employee Scheduling

An attempt at a workable solution to the employee scheduling problem as it
actually appears in Indian work systems, and in particular for workers who are
paid by the day or by the hour rather than on a monthly salary.

For a daily-wage or hourly worker the roster *is* the pay slip. How many duties
a person gets, how many hours those duties add up to, and whether the work is
spread evenly across the month decide what they earn. A roster that quietly
gives one worker eighteen duties and another eight is not merely untidy, it is
an income decision. So this engine treats duty and hour counts per person as
first-class quantities: it can hold every worker to a minimum number of duties
or hours, cap the maximum, and balance the spread between the busiest and the
quietest person, alongside the usual coverage requirements.

The other half of the problem is that a roster has to satisfy two separate
bodies of rules at once. There are the rules the staff administration imposes —
who is qualified for which post, who is on leave, which duties are already
fixed, how many people each post needs on each shift, how many nights anyone
should do in a row, which shift may not follow which. And there are the
statutory limits from labour law: a ceiling on hours in a day and in a week, a
weekly rest day, a minimum rest gap between consecutive shifts, limits on
continuous stretches of work, and overtime treated as an exception rather than
the norm. The specifics differ by state and by the kind of establishment, so
nothing statutory is hard-coded here. Every constraint is a configured rule with
a scope, a severity and a weight, which means the same engine serves a factory
under one set of limits and a shop or an institution under another.

Rules are declared hard or soft. Hard rules — statutory ceilings, leave,
qualification — must hold for a roster to be called legal. Soft rules are the
preferences and the fairness goals, and the solver trades them against each
other by weight when they conflict, then reports exactly what it gave up and why.

## Status

The scheduling engine is built and verified, it is reachable over HTTP, and it
now reads rules written as ordinary prose. It generates a month-long roster from
an arbitrary start date for dozens of staff holding multiple roles across three
shifts a day, understands 25 kinds of rule, and reports every breach in the
admin's own wording. On the test instance — 44 staff, 31 days, 612 person-shifts,
33 rules — it produces a fully legal roster with no hard breach, independently
re-audited by a second implementation of the rules that reads only the output.
The same month solved through the API in 25 seconds returns the same verdict.

The admin's page has been started. `frontend/index.html` is served by
`roster.cli serve`, and it walks the month in six steps — period, staff, shifts,
rules, check, roster. It opens the sample month from the API, reads it back in the
admin's terms, asks `POST /validate` whether the month is possible at all, and
then generates it: the duty register itself, dates across and staff down, with
weekends shaded, nights in violet, each person's duties, hours, nights and
weekends ruled off at the right edge, a head count under every day, and
underneath it every rule the engine had to give ground on — grouped by rule, worst
first, with the penalty each one cost.

Step four is the questionnaire. The page asks `GET /schema` what the engine
understands and builds the form from the answer, so a rule type added to the
engine appears in the page without the page being touched: 25 kinds grouped into
seven families, each with its plain-English help and a worked example, and a field
per parameter drawn from its declared kind — a number box, a yes/no pair, a
dropdown of shifts or roles, or a row of day chips with the weekends marked. The
admin picks who a rule applies to (everyone, named people, a role, a contract),
whether it is unbreakable or a preference, and how much a preference is worth. Every
add, edit and removal is put to `POST /validate` before it is kept, so a rule the
engine would refuse never enters the month; the refusal appears next to the field
in the engine's own words, and the register of rules and the feasibility check on
step five stay in step with each other.

Still to come: pasting rules as free prose into the questionnaire for review, and
CSV export.

## Running it

Everything is standard library Python, no dependencies to install.

```
cd backend
python -m roster.cli demo --seconds 30 --coverage --roles
python -m roster.cli rules
python -m roster.cli parse --sample "Nobody may work more than 6 days in a row"
python -m roster.cli serve --port 8000
python -m unittest discover -s tests -t .
```

The first command solves the built-in month and prints the roster grid, the
per-person workload and the rule report. The second lists every rule type the
engine understands. The third reads rules written as prose into draft rules, and
takes them as arguments, from a file with `--file`, or on standard input. The
fourth starts the API. The last runs the test suite — 395 tests, about a minute —
and the `-t .` is required.

With the server up, open <http://127.0.0.1:8000/> for the admin's page. It is one
self-contained HTML file with no build step and no dependencies of its own, which
is why it is plain JavaScript rather than React: nothing could be installed from a
package registry in the environment this was written in, and a page that cannot be
run cannot be verified either. The same screens can be rebuilt as React components
later without the API changing.

Generated rosters, reports and CSV exports are written to a `roster-output`
folder beside this project, never inside it, so results stay out of the
repository. Override with `--out-dir` or `$ROSTER_OUT_DIR`.

## Rules written as prose

The administration's rules arrive as sentences, not as forms, so `POST /parse`
and `roster.cli parse` read those sentences into draft rules. A draft is a
proposal: it carries the rule it would become, the words it came from, every
assumption that was made in reading it, and a confidence. Nothing is drafted
unless it really builds against the instance, so a draft the admin confirms
cannot fail later. "Nobody may work more than 6 days in a row and no more than 48
hours a week" comes back as two rules with a note saying the line was split.
"Staff 07 is on leave from 15 to 19 September" resolves the person and expands
the dates.

Where a sentence cannot be held honestly, it is refused with the reason rather
than guessed at: a group that is not in the staff data, a staff number nobody
has, a date outside the month, a daily hours cap that is really a shift length.
A dozen refusals of this kind are covered by tests. The drafts are the admin's to
accept, edit or drop — the structured rules stay the single source of truth.

A rule that could never be satisfied is refused wherever it comes from — the
questionnaire, prose, or a hand-written instance. Every parameter is held to the
floor its own specification advertises, so a run of zero days or a negative rest
period is turned away, and any rule with a floor and a ceiling is refused when the
floor sits above the ceiling: "min 20 is above max 4, so no roster can satisfy it".
The alternative is worse than an error message, because a contradiction like that
solves as an unavoidable breach on every roster and the admin is left reading a
report that blames the staff for a typo. Contradictions *between* rules are a
different matter and are not treated this way: each one is satisfiable alone, so
they are left to the feasibility check and the violation report.

## The API

`GET /health`, `/schema`, `/rules` and `/sample` are the read side: the schema
and rule catalogue are what the questionnaire draws itself from, and `/sample`
hands back a complete worked instance so the form has something real to open
with. `POST /validate` says whether an instance is satisfiable before anybody
waits on a search, `/parse` reads rules written as prose into drafts, `/solve`
generates a roster, `/evaluate` scores a roster somebody else wrote without
touching it, and `/repair` takes a submitted roster and improves it in place.
Every response carries the roster, the score, the coverage, the per-person
workload and the full violation list; failures come back as `{"error", "field"}`
with a 4xx, never as a traceback.

The server binds to loopback only and has **no authentication** by default,
which is safe on your own machine and nowhere else. Pass `--token` to require a
shared secret on every route but `/health`; a non-loopback bind without one is
refused unless you add `--insecure`. Request bodies are capped, only two
searches run at once and a third is told to retry, and the browser origin for
cross-origin calls has to be named explicitly with `--cors`.

`--fastapi` serves the same endpoints through FastAPI and uvicorn if you have
them installed; see `backend/requirements-optional.txt`. The stdlib server is
the one that has been tested here.

## Licence

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
