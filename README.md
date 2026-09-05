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
weekends shaded, every shift in a colour of its own and nights filled solid, each
person's duties, hours, nights and weekends ruled off at the right edge, a head
count under every day, and underneath it every rule the engine had to give ground
on — grouped by rule, worst first, with the penalty each one cost.

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
roles they hold, how to reach them, their longest run, the shifts they worked, their
thirty-one days in a strip, and every rule broken on their account.

Step four takes the rules in the officials' own words, and only that way. The admin
writes or pastes the order a line at a time; the page sends it to `POST /parse` with
the month and lays the reading out as proposals: what each line was quoted as, what
rule it would become in the admin's own terms, every assumption the reading made,
and how sure it was. A proposal can be accepted as it stands, opened and corrected
first, or discarded; a line that could not be read says why and offers the nearest
kinds instead. Nothing reaches the register without being put to `POST /validate`,
and the officials' own wording becomes the label the breach report will use, so what
comes back reads like the circular rather than like a rule type.

Some sentences honestly say two things at once. "No more than 4 nights" can mean
four nights in the month or four nights in a row, and both are proper rules; a
number named after "more than" can be the floor the office means or the ceiling it
means; a limit with no window said can be a week or a month. Where a line reads
more than one way the page does not pick. It shows every reading side by side, each
one saying in the engine's words what choosing it would mean, and the admin presses
the one they meant — nothing is chosen for them. The plain accept button is withheld
on such a line, and accepting the whole page at once steps over it rather than
guessing, so a reading only reaches the register by being pressed. Once pressed it
is an ordinary rule: correctable on the slip, and removable like any other.

There is no form to fill in beside it. What the page offers instead is folded away
under the box: every kind of rule the engine understands, grouped into families with
its plain-English help and a sentence the parser is guaranteed to read, and a button
that drops that sentence into the box to be edited. The list comes from
`GET /schema`, so a rule type added to the engine shows up in the page without the
page being touched — 25 kinds at present. The parameter-by-parameter slip is still
there for correcting a reading: it opens on a proposal the engine read wrongly, or
on a rule already kept, where a number or a shift the parser took the wrong way can
be put right before the rule goes on the month.

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

The roll is editable in the same spirit. A name, a staff number and the roles a
person holds can all be corrected, a contact number and an email address can be kept
beside them for the office's own use — the engine never reads either — people can be
taken on or taken off, and the consequences are handled rather than left to the
admin. Because every rule
names a person by staff number, renaming one rewrites every rule that named them in
the same breath, and the slip says how many rules that will be before the change is
made. Removing somebody trims them out of the rules that still name other people
and drops only the rules that would then name nobody, saying which; the removal can
be undone, putting the person back where they stood on the roll with their rules
restored. The roll can be emptied down to nobody — the month simply goes back to
being held on the desk until somebody is on it again — while a staff number already
taken, or one holding characters no rule could name, is refused on the page without
troubling the engine, as is a contact number too short to dial or an address with no
`@` in it. What the page suggests for the next person it reads off the roll itself:
the office's own numbering carried on a step, never an invented example.

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
outside the month hatched, rest days tinted, each shift in its own colour and nights
filled solid — with each duty
giving its shift, its clock and the role it is worked as, and each day the rules
already speak to marked on the day itself in the officials' own wording: on leave,
day requested off, duty already fixed. Their duties, hours, nights, weekends and
longest run are totalled above it. Before a roster exists the calendar still shows
what the rules fix, so the month can be read before it is built.

The page is laid out as a wall planner: a deep ink frame with the six steps pinned
down the left as tabs, the current one joined to a white working sheet that holds the
month. The colour code is the one thing the eye has to learn, and it is drawn from
the office's own list rather than from the letters — the first shift the admin
enters takes the first colour, the second the second, and every place a duty appears
uses the same one, whether that is a cell in the duty register, a day on somebody's
calendar, a square in their month strip or the key that names it. A shift that counts
as a night is filled solid in its colour instead of tinted. Type is system-ui
throughout, so no font is fetched, with tabular figures wherever numbers are meant to
line up in a column.

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
fourth starts the API. The last runs the test suite — 434 tests, about a minute —
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
roles and three shifts, nine staff on the office's own numbering with a contact
number and an address kept beside the first of them, the demand laid across working
days and rest days, and two mandatory rules written as prose and read back through
`POST /parse` — then it has the real
engine judge the month, solve it, and confirms the roster covers exactly the dates
asked for with no hard rule broken and nobody working more days in a row than the
admin allowed. Along the way it checks that a half-built month is never sent
anywhere, that an impossible span, an unusable figure or a contact number that could
never be dialled is refused before it is
sent, that a month the engine cannot read comes back refused in the engine's own
words, that a role or shift something still holds cannot be removed, that starting
a month over empties the desk and takes the old roster with it, that every duty on
the register carries the colour of its shift, that a line which reads two ways is
offered as readings the admin presses — neither the plain accept button nor
accepting the whole page will take one — and that the reading pressed is the one
that reaches the register, and that one
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
the dates. Dates are read the way an office writes them: `2026-09-15`, `18/09/2026`,
`23.09.2026`, "15 September", "the 20th", a range as "15 to 19 September", "15-19
September", "from the 15th to the 19th of September" or "between 15 and 19 September",
a list as "15, 16 and 19 September", "for 4 days from the 22nd", and a weekday name as
every such day in the period. A range written backwards is refused rather than quietly
swapped, and "between 1 and 3 people" is still a headcount — only a date-shaped pair
becomes a range.

Where a sentence cannot be held honestly, it is refused with the reason rather
than guessed at: a group that is not in the staff data, a staff number nobody
has, a date outside the month, a daily hours cap that is really a shift length.
A sentence that sorts people by a personal attribute — gender, seniority, age,
religion, caste, marital status, a health condition — is refused for the same
reason, because the staff records carry no such field: a rule can cover named
staff, a role, a contract type, or everyone. Where the office has defined the
group as a cadre of its own, that cadre is a role and the rule lands on it.
A dozen refusals of this kind are covered by tests. The drafts are the admin's to
accept, edit or drop — the structured rules stay the single source of truth. On the
page they arrive as proposals on step four, and a ten-line circular put through the
running server read eight lines, took them onto a 33-rule month and generated a
legal roster from all 41.

The reader is meant to take the office's wording rather than the office learning
the reader's. A limit may sit anywhere in the sentence — "at most 6 days in a row",
"6 days in a row at most", "days in a row: 6 maximum", "6 is the ceiling" all set
the same bound — and the words that set one are read widely: capped at, limited to,
cap hours at 48, must not exceed, no higher than, up to, no fewer than, at the very
least. A window can be a calendar week or a rolling one, however it is worded:
"in any 7 days", "in any 7 day window", "in any window of 7 days", "in any 7-day
period". Duties in a week are read as working days in a week, because a person
works one duty a day in this model, and the reading says so. One sentence may carry
two limits on different things — "at most 48 hours a week and 5 duties" — and the
second half borrows the first half's limit word rather than being dropped. Two
promises hold throughout: a sentence that names a number is never read as a total
ban, and anything the reading could not keep is reported as an assumption instead of
disappearing — a floor on working days in a week, for instance, is not a rule type,
so the ceiling is taken and the floor is named as dropped.

Shifts and cadres are named the way the office names them. A duty may be called a
shift, a slot, a duty, a turn, a watch or a relay, and a run of them — "5 shifts in
a row", "5 slots in a row", "5 duties at a stretch" — is a run of working days,
while "3 night shifts in a row" stays a run of that one shift. An office that codes
its shifts by a single letter is understood as long as the words frame the letter as
one: "slot B", "shift B" and "the B shift" all find shift B, while the article in
"a day off" does not, even in an office whose morning shift is coded A. A cadre is
matched however it is pluralised, so "lady guards" reaches a Lady Guard role the
office has actually defined — and where no such group is on the staff records the
same sentence is refused rather than widened to everybody.

A rule that could never be satisfied is refused wherever it comes from — prose, a
correction made on the page, or a hand-written instance. Every parameter is held to
the floor its own specification advertises, so a run of zero days or a negative rest
period is turned away, and any rule with a floor and a ceiling is refused when the
floor sits above the ceiling: "min 20 is above max 4, so no roster can satisfy it".
The alternative is worse than an error message, because a contradiction like that
solves as an unavoidable breach on every roster and the admin is left reading a
report that blames the staff for a typo. Contradictions *between* rules are a
different matter and are not treated this way: each one is satisfiable alone, so
they are left to the feasibility check and the violation report.

## The API

`GET /health`, `/schema`, `/rules` and `/sample` are the read side: the schema and
rule catalogue are where the page gets the wordings it offers and the fields it uses
to correct a reading, and `/sample`
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
