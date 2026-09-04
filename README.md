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
`roster.cli serve`, with `styles.css` and `app.js` beside it, and it walks the month
in six steps — period, staff, shifts, rules, check, roster. It opens on an empty
desk: nothing is assumed and no example data is ever fetched. Step one asks for the
first day, how many days the month runs and which weekdays are the weekly rest, and
the month it opens is genuinely blank — no roles, no shifts, nobody on the roll, no
demand, no rules. The steps that follow fill it in the admin's own terms: role codes
and the roll, the shifts in a day and how many of each role each one needs, and the
rules. A half-built month is held on the desk rather than sent anywhere, because the
engine cannot read one; from the first person onwards every change is put to
`POST /validate` and kept only if the engine agrees. Once the month stands up it is
generated: the duty register itself, dates across and staff down, with
weekends shaded, nights in violet, each person's duties, hours, nights and
weekends ruled off at the right edge, a head count under every day, and
underneath it every rule the engine had to give ground on — grouped by rule, worst
first, with the penalty each one cost.

That register can be searched and questioned rather than only read. A name or a
staff number narrows the sheet to whoever matches, a role narrows it to the people
holding that role, and one checkbox narrows it to the people a rule was actually
broken for — while the head count under each day keeps counting the whole roster,
because it describes the month and not the search. Pointing at a duty rules a
crosshair down its day and across its row and reads the duty out in the margin: who,
which shift, which role, which date. Every rule in the breach report is pressable,
and pressing one marks in red what it cost — the particular duties where somebody's
rest was cut short, a whole row where somebody worked too many weekends, the head of
a day that went understaffed — with a line in the margin saying in words how many
duties and how many people were marked, and saying so plainly when the search has
hidden them. A breach about the month as a whole admits that instead of pretending
to point at a cell. Opening a name gives that person's month on its own slip: the
roles they hold, their contract, their longest run, the shifts they worked, their
thirty-one days in a strip, and every rule broken on their account.

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

Rules can also be pasted in as the officials wrote them. The same step takes the
circular a line at a time, sends it to `POST /parse` with the month, and lays the
reading out as proposals: what each line was quoted as, what rule it would become
in the admin's own terms, every assumption the reading made, and how sure it was.
A proposal can be accepted as it stands, opened in the questionnaire and corrected
first, or discarded; a line that could not be read says why and offers the nearest
kinds to fill in by hand instead. Nothing reaches the register without being put to
the engine, and the officials' own wording becomes the label the breach report will
use, so what comes back reads like the circular rather than like a rule type.

Nothing on the page is read-only any more. The month itself can be moved: step one
takes a new first day and a new length, works out what that would mean before
anything is sent, and says so in a ledger — how far the month moves, how many days
it becomes, how many dated rules travel with it, and which would be trimmed or lost
because their dates now fall outside. Leave, days already asked off and duties
already fixed are shifted by the same number of days the month moved, a rule that
only partly fits keeps the dates that still land inside, and a rule left with no
dates at all is named in red before it goes rather than after. The demand moves
with the calendar too: where the month has one shape for working days and another
for rest days, the new month is laid out to its own weekends, and where the demand
is irregular each added day repeats the same weekday a week earlier. The page says
which of the two it did.

The roll is editable in the same spirit. A name, a staff number, the roles a person
holds and their contract can all be corrected, people can be taken on or taken off,
and the consequences are handled rather than left to the admin. Because every rule
names a person by staff number, renaming one rewrites every rule that named them in
the same breath, and the slip says how many rules that will be before the change is
made. Removing somebody trims them out of the rules that still name other people
and drops only the rules that would then name nobody, saying which; the removal can
be undone, putting the person back where they stood on the roll with their rules
restored. The roll can be emptied down to nobody — the month simply goes back to
being held on the desk until somebody is on it again — while a staff number already
taken, or one holding characters no rule could name, is refused on the page without
troubling the engine. What the page suggests for the next person it reads off the
roll itself: the office's own numbering carried on a step, and the contract most of
the roll is already on, never an invented example.

Roles and shifts are made on the page the same way, and can be taken off it. A role
is a code and a printed name; a shift is a letter, a name, a clock, a length and
whether it counts as a night. Neither code can be edited once it exists, because the
demand and the rules are keyed to it, and neither can be removed while anything
still holds it — the page says what does, whether that is people on the roll, lines
of demand or rules that name it, and asks for those to be taken off first.

Shift clocks are editable too — when a shift starts, how long it runs, and whether
it counts as a night, which is what the night rules and the rest gaps are read
against rather than the hour on the clock. The letter that names a shift stays
fixed, because every line of demand and every rule that mentions a shift is keyed
to it. A time that is not a time, or a length under a quarter of an hour or over
twenty-four, is refused before it is sent; anything the page does accept still goes
to `POST /validate` and is kept only if the engine agrees.

Step three also answers the question an admin actually asks, which is about one
person rather than the whole sheet. Any name or staff number brings up that person's
month as a calendar — the weeks laid out under the weekday the month starts on, days
outside the month hatched, rest days tinted, nights in violet — with each duty
giving its shift, its clock and the role it is worked as, and each day the rules
already speak to marked on the day itself in the officials' own wording: on leave,
day requested off, duty already fixed. Their duties, hours, nights, weekends and
longest run are totalled above it. Before a roster exists the calendar still shows
what the rules fix, so the month can be read before it is built.

Still to come: CSV export and print styles.

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
fourth starts the API. The last runs the test suite — 396 tests, about a minute —
and the `-t .` is required.

With the server up, open <http://127.0.0.1:8000/> for the admin's page. It is three
plain files served as they are — `index.html` is the markup, `styles.css` the
stylesheet, `app.js` the behaviour — with no build step and no dependencies of its
own. That last part is why it is plain JavaScript rather than React: nothing could be
installed from a package registry in the environment this was written in, and a page
that cannot be run cannot be verified either. The same screens can be rebuilt as
React components later without the API changing.

The page has its own end-to-end check, which needs nothing but Node and a running
engine:

```
node frontend/checks/live.cjs
```

It loads `app.js` with a stub document, points it at the server on port 8000
(`PORT=…` for another), and drives the page's own functions rather than a copy of
them. It builds a month from nothing the way an admin would: an empty desk that
assumes nothing, a month opened on a chosen first day for a chosen length, three
roles and three shifts, nine staff on the office's own numbering, the demand laid
across working days and rest days, and two mandatory rules — then it has the real
engine judge the month, solve it, and confirms the roster covers exactly the dates
asked for with no hard rule broken and nobody working more days in a row than the
admin allowed. Along the way it checks that a half-built month is never sent
anywhere, that an impossible span or an unusable figure is refused before it is
sent, that a month the engine cannot read comes back refused in the engine's own
words, that a role or shift something still holds cannot be removed, that starting
a month over empties the desk and takes the old roster with it, and that one
person's calendar reads off the roster the engine actually returned. It also
asserts, start to finish, that no example data is ever fetched. It exits non-zero
if any of that stops holding.

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
accept, edit or drop — the structured rules stay the single source of truth. On the
page they arrive as proposals on step four, and a ten-line circular put through the
running server read eight lines, took them onto a 33-rule month and generated a
legal roster from all 41.

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
hands back a complete worked instance for the tests and the `demo` command. The
admin's page never calls it — it starts from nothing. `POST /validate` says whether
an instance is satisfiable before anybody
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
