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

The scheduling engine is built and verified. It generates a month-long roster
from an arbitrary start date for dozens of staff holding multiple roles across
three shifts a day, understands 24 kinds of rule, and reports every breach in
the admin's own wording. On the test instance — 44 staff, 31 days, 612
person-shifts, 32 rules — it produces a fully legal roster with no hard breach,
independently re-audited by a second implementation of the rules that reads only
the output.

Still to come: the HTTP API, a parser that turns rules written as free text into
draft rules for the admin to confirm, and the web questionnaire the admin fills
in.

## Running it

Everything is standard library Python, no dependencies to install.

```
cd backend
python -m roster.cli demo --seconds 30 --coverage --roles
python -m roster.cli rules
python -m unittest discover -s tests -t .
```

The first command solves the built-in month and prints the roster grid, the
per-person workload and the rule report. The second lists every rule type the
engine understands. The third runs the test suite; the `-t .` is required.

Generated rosters, reports and CSV exports are written to a `roster-output`
folder beside this project, never inside it, so results stay out of the
repository. Override with `--out-dir` or `$ROSTER_OUT_DIR`.

## Licence

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
