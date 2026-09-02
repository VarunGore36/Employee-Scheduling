"""Command line front end. ``python -m roster.cli --help``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import api, report
from .generate import small_instance, university_instance
from .rules import RuleSet
from .ruleinfo import catalog
from .schema import Instance
from .search import Solver, SolverOptions
from .service import ServiceError, evaluate_payload, repair_payload, solve_payload, validate_payload
from .service import parse_payload, schema_payload
from .state import RosterState


def _read_json(path: str) -> dict:
    if path == "-":
        return json.load(sys.stdin)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"no such file: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}")


# Generated files are results, not source, so they never land inside the project.
DEFAULT_OUT_DIR = Path(__file__).resolve().parents[3] / "roster-output"


def _out_dir(args) -> Path:
    chosen = getattr(args, "out_dir", None) or os.environ.get("ROSTER_OUT_DIR")
    return Path(chosen).expanduser() if chosen else DEFAULT_OUT_DIR


def _resolve(args, path: str | None) -> str | None:
    """A bare filename lands in the output folder; a real path is left alone."""
    if not path or path == "-":
        return path
    given = Path(path).expanduser()
    if given.is_absolute() or len(given.parts) > 1:
        return str(given)
    return str(_out_dir(args) / given)


def _write(path: str | None, text: str, what: str) -> None:
    if not path:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")
    print(f"wrote {what} to {path}", file=sys.stderr)


def _dump(path: str | None, data: dict, what: str) -> None:
    _write(path, json.dumps(data, indent=2), what)


def _options(args) -> SolverOptions:
    return SolverOptions(
        seed=args.seed,
        max_seconds=args.seconds,
        verbose=args.verbose,
        max_iterations=getattr(args, "iterations", 0) or 0,
    )


def _instance(args) -> Instance:
    """From a file when given one, otherwise the built-in synthetic case."""
    if getattr(args, "instance", None):
        data = _read_json(args.instance)
        return Instance.from_dict(data.get("instance", data))
    if getattr(args, "small", False):
        return small_instance()
    return university_instance(
        start=getattr(args, "start", None) or "2026-09-12",
        num_days=getattr(args, "days", None) or 31,
        num_employees=getattr(args, "employees", None) or 44,
        seed=getattr(args, "instance_seed", None) or 7,
    )


def _emit(state: RosterState, evaluation, rules: RuleSet, args) -> None:
    """Text to the terminal, machine formats to whatever files were asked for."""
    if args.format == "json":
        body = json.dumps(report.report_dict(state, evaluation, rules), indent=2)
        label = "report json"
    else:
        sections = ["summary", "grid", "workload"]
        if args.coverage:
            sections.append("coverage")
        sections.append("violations")
        body = report.text_report(state, evaluation, rules,
                                  show_role=args.roles, sections=tuple(sections))
        label = "text report"
    print(body)
    if args.csv or args.duties or args.breaches or args.out:
        print(file=sys.stderr)          # keep the file list clear of the report
    _write(_resolve(args, args.csv), report.roster_csv(state), "roster csv")
    _write(_resolve(args, args.duties), report.assignments_csv(state), "duty list csv")
    _write(_resolve(args, args.breaches), report.violations_csv(evaluation), "violation csv")
    _write(_resolve(args, args.out), body, label)


def cmd_solve(args) -> int:
    inst = _instance(args)
    print(inst.summary(), file=sys.stderr)
    solver = Solver(inst, _options(args))
    result = solver.solve()
    print(
        f"construction {result.construction_cost:,.1f} -> final {result.cost:,.1f} "
        f"in {result.seconds:.1f}s over {result.iterations:,} moves "
        f"({result.accepted:,} accepted)",
        file=sys.stderr,
    )
    _emit(result.state, result.evaluation, solver.rules, args)
    if args.instance_out:
        _dump(_resolve(args, args.instance_out), inst.to_dict(), "instance json")
    if args.roster_out:
        _dump(_resolve(args, args.roster_out), result.state.to_dict(), "roster json")
    return 0 if result.feasible else 1


def cmd_demo(args) -> int:
    """The verification run: synthetic university month, solved and reported."""
    args.instance = None
    return cmd_solve(args)


def cmd_generate(args) -> int:
    inst = _instance(args)
    print(inst.summary(), file=sys.stderr)
    payload = {"instance": inst.to_dict()}
    if args.out:
        _dump(_resolve(args, args.out), payload, "instance json")
    else:
        print(json.dumps(payload, indent=2))
    return 0


def cmd_evaluate(args) -> int:
    inst = _instance(args)
    roster = _read_json(args.roster)
    payload = {"instance": inst.to_dict(), "roster": roster.get("roster", roster)}
    out = evaluate_payload(payload)
    if args.format == "json":
        print(json.dumps(out, indent=2))
    else:
        rules = RuleSet(inst)
        state = RosterState.from_dict(inst, payload["roster"])
        _emit(state, rules.evaluate(state), rules, args)
    return 0 if out["score"]["feasible"] else 1


def cmd_repair(args) -> int:
    inst = _instance(args)
    roster = _read_json(args.roster)
    payload = {
        "instance": inst.to_dict(),
        "roster": roster.get("roster", roster),
        "options": {"seed": args.seed, "max_seconds": args.seconds, "verbose": args.verbose},
    }
    out = repair_payload(payload)
    before, after = out["before"], out["score"]
    print(f"before {before['cost']:,.1f} ({before['hard_violations']} hard) -> "
          f"after {after['cost']:,.1f} ({after['hard_violations']} hard)", file=sys.stderr)
    if args.format == "json":
        print(json.dumps(out, indent=2))
    else:
        rules = RuleSet(inst)
        state = RosterState.from_dict(inst, out["roster"])
        _emit(state, rules.evaluate(state), rules, args)
    if args.roster_out:
        _dump(_resolve(args, args.roster_out), out["roster"], "repaired roster json")
    return 0 if after["feasible"] else 1


def cmd_validate(args) -> int:
    inst = _instance(args)
    out = validate_payload({"instance": inst.to_dict()})
    if args.format == "json":
        print(json.dumps(out, indent=2))
        return 0 if out["ok"] else 1
    info = out["instance"]
    print(f"{info['name']}: {info['employees']} staff, {info['num_days']} days from "
          f"{info['start']}, {info['demand_person_shifts']} person-shifts "
          f"({info['utilisation']:.0%} of capacity)")
    print(f"{info['hard_rules']} hard rules, {info['soft_rules']} soft")
    for role, cap in sorted(out["capacity_by_role"].items()):
        print(f"  {role:>5}: {cap['qualified_staff']:>3} qualified, "
              f"{cap['person_days_demanded']:>4} person-days needed of "
              f"{cap['person_days_available']:>5} available")
    for line in out["warnings"]:
        print(f"  warning: {line}")
    for line in out["problems"]:
        print(f"  PROBLEM: {line}")
    print("ok" if out["ok"] else "not satisfiable as stated")
    if args.list_rules:
        print("\nrules as the engine read them:")
        for line in out["rules"]:
            print(f"  {line}")
    return 0 if out["ok"] else 1


def cmd_schema(args) -> int:
    payload = {}
    if getattr(args, "instance", None):
        data = _read_json(args.instance)
        payload = {"instance": data.get("instance", data)}
    out = schema_payload(payload)
    if args.out:
        _dump(_resolve(args, args.out), out, "form schema json")
    else:
        print(json.dumps(out, indent=2))
    return 0


def _rules_text(args) -> str:
    """The policy text, from the words given, from a file, or from stdin."""
    if getattr(args, "text", None):
        return "\n".join(args.text)
    if args.file and args.file != "-":
        try:
            return Path(args.file).expanduser().read_text(encoding="utf-8")
        except FileNotFoundError:
            raise SystemExit(f"no such file: {args.file}")
    if args.file == "-" or not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("give the rules as arguments, with --file, or on stdin")


def _params_text(rule: dict) -> str:
    parts = []
    for key, value in rule["params"].items():
        parts.append(f"{key}={len(value)} values" if isinstance(value, list)
                     and len(value) > 4 else f"{key}={value}")
    return ", ".join(parts) or "no parameters"


def _scope_text(rule: dict) -> str:
    scope = rule.get("scope") or {}
    if scope.get("kind", "all") == "all":
        return "everyone"
    return f"{scope['kind']} {', '.join(scope.get('ids') or [])}"


def _print_drafts(out: dict) -> None:
    for draft in out["drafts"]:
        rule = draft["rule"]
        if rule:
            print(f"{draft['line']:>4}  {rule['severity']:<4} {draft['confidence']:.2f}  "
                  f"{rule['type']}  {_params_text(rule)}  [{_scope_text(rule)}]")
        else:
            print(f"{draft['line']:>4}  --   ----  not read: {draft['problem']}")
        print(f"      | {draft['text']}")
        for note in draft["assumptions"]:
            print(f"      . {note}")
        for name in draft["suggestions"]:
            print(f"      > nearest rule type: {name}")
    c = out["counts"]
    tail = "" if c["checked_against_instance"] else ("; with no instance nothing was "
                                                    "checked against real staff, "
                                                    "shifts or dates")
    print(f"\n{c['drafted']} of {c['statements']} statements drafted "
          f"({c['hard']} hard, {c['soft']} soft), {c['unparsed']} not read{tail}")


def cmd_parse(args) -> int:
    """Rules written as prose into draft rules the admin still has to confirm."""
    payload = {"text": _rules_text(args)}
    if args.instance:
        data = _read_json(args.instance)
        payload["instance"] = data.get("instance", data)
    elif args.sample:
        payload["instance"] = _instance(args).to_dict()
    out = parse_payload(payload)
    if args.format == "json":
        print(json.dumps(out, indent=2))
    else:
        _print_drafts(out)
    _dump(_resolve(args, args.out), out, "draft rules json")
    if args.rules_out:
        _dump(_resolve(args, args.rules_out), {"rules": out["rules"]}, "rule list json")
    return 0 if not out["counts"]["unparsed"] else 1


DEFAULT_UI_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _ui_dir(args) -> Path | None:
    """Explicit folder if given, otherwise the bundled frontend when it exists."""
    if getattr(args, "ui", None):
        chosen = Path(args.ui).expanduser()
        if not (chosen / "index.html").is_file():
            raise SystemExit(f"no index.html in {chosen}")
        return chosen
    if (DEFAULT_UI_DIR / "index.html").is_file():
        return DEFAULT_UI_DIR
    return None


def cmd_serve(args) -> int:
    """Run the HTTP API. Loopback and no token by default, which is a private server."""
    if args.fastapi:
        from .fastapi_app import serve as serve_fastapi
        if args.ui:
            print("--ui is ignored under --fastapi; mount static files yourself",
                  file=sys.stderr)
        return serve_fastapi(args.host, args.port, args.token, args.cors)
    return api.serve(
        api.ApiConfig(host=args.host, port=args.port, token=args.token,
                      cors_origin=args.cors, ui_dir=_ui_dir(args),
                      max_body=args.max_body, max_concurrent=args.max_searches,
                      quiet=args.quiet),
        insecure=args.insecure,
    )


def cmd_rules(args) -> int:
    """Human-readable catalogue - what the admin will be asked, in one screen."""
    for entry in catalog():
        params = ", ".join(
            f"{p['name']}{'' if p.get('required') else '?'}" for p in entry["params"]
        ) or "no parameters"
        print(f"{entry['type']}  [{entry['applies_to']}, {entry['default_severity']} by default]")
        print(f"    {entry['label']}")
        print(f"    {entry['help']}")
        print(f"    params: {params}")
        if entry.get("example"):
            print(f"    example: {entry['example']}")
        print()
    print(f"{len(catalog())} rule types registered")
    return 0


def _add_instance_args(p, allow_file=True) -> None:
    if allow_file:
        p.add_argument("-i", "--instance", help="instance JSON file, or - for stdin")
    p.add_argument("--start", help="first day, ISO date (synthetic instance)")
    p.add_argument("--days", type=int, help="horizon length in days (synthetic instance)")
    p.add_argument("--employees", type=int, help="headcount (synthetic instance)")
    p.add_argument("--instance-seed", type=int, help="synthetic instance seed")
    p.add_argument("--small", action="store_true", help="use the 12-person test instance")


def _add_solver_args(p) -> None:
    p.add_argument("--seconds", type=float, default=20.0, help="search time budget")
    p.add_argument("--seed", type=int, default=12345, help="search seed")
    p.add_argument("--iterations", type=int, default=0, help="cap on moves (0 = time only)")
    p.add_argument("-v", "--verbose", action="store_true", help="log reheats and polish")


def _add_output_args(p) -> None:
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--roles", action="store_true", help="show role as well as shift in the grid")
    p.add_argument("--coverage", action="store_true", help="include the coverage table")
    p.add_argument("-o", "--out", help="write the report here, in --format")
    p.add_argument("--csv", help="write the roster grid as CSV here")
    p.add_argument("--duties", help="write one row per duty as CSV here")
    p.add_argument("--breaches", help="write the violation list as CSV here")
    p.add_argument("--roster-out", help="write just the roster as JSON here")
    p.add_argument("--instance-out", help="write the instance as JSON here")
    _add_out_dir_arg(p)


def _add_out_dir_arg(p) -> None:
    p.add_argument("--out-dir", metavar="DIR",
                   help=f"folder for bare output filenames (default {DEFAULT_OUT_DIR}, "
                        "or $ROSTER_OUT_DIR); generated files are kept out of the "
                        "project so they are never committed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="roster",
        description="Roster generator: rules in, legal roster out.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="exit status is 0 when the roster breaks no hard rule, 1 when it does",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("solve", help="generate a roster")
    _add_instance_args(p)
    _add_solver_args(p)
    _add_output_args(p)
    p.set_defaults(func=cmd_solve)

    p = sub.add_parser("demo", help="solve the built-in synthetic university month")
    _add_instance_args(p, allow_file=False)
    _add_solver_args(p)
    _add_output_args(p)
    p.set_defaults(func=cmd_demo, instance=None)

    p = sub.add_parser("generate", help="write a synthetic instance to JSON")
    _add_instance_args(p, allow_file=False)
    p.add_argument("-o", "--out", help="output file (default stdout)")
    _add_out_dir_arg(p)
    p.set_defaults(func=cmd_generate, instance=None)

    p = sub.add_parser("evaluate", help="score an existing roster against the rules")
    _add_instance_args(p)
    p.add_argument("-r", "--roster", required=True, help="roster JSON file")
    _add_output_args(p)
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("repair", help="improve an existing roster in place")
    _add_instance_args(p)
    p.add_argument("-r", "--roster", required=True, help="roster JSON file")
    _add_solver_args(p)
    _add_output_args(p)
    p.set_defaults(func=cmd_repair)

    p = sub.add_parser("validate", help="check an instance is satisfiable before solving")
    _add_instance_args(p)
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--list-rules", action="store_true", help="print every rule as read")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("schema", help="dump the questionnaire schema for the frontend")
    p.add_argument("-i", "--instance", help="instance JSON, to fill dropdown options")
    p.add_argument("-o", "--out", help="output file (default stdout)")
    _add_out_dir_arg(p)
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("parse", help="read rules written as free text into draft rules",
                       description="Reads policy prose into draft rules for the admin "
                                   "to confirm. Exit status is 1 if any statement "
                                   "could not be read.")
    p.add_argument("text", nargs="*", help="the rules, one statement per argument")
    p.add_argument("-f", "--file", help="read the rules from this file, or - for stdin")
    p.add_argument("-i", "--instance", help="instance JSON, so names and dates resolve")
    p.add_argument("--sample", action="store_true",
                   help="read against the built-in synthetic instance")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("-o", "--out", help="write every draft as JSON here")
    p.add_argument("--rules-out", help="write just the accepted rules as JSON here")
    _add_out_dir_arg(p)
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("rules", help="list every rule type the engine understands")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("serve", help="run the HTTP API over the same engine")
    p.add_argument("--host", default="127.0.0.1",
                   help="interface to bind; the default is this machine only")
    p.add_argument("--port", type=int, default=api.DEFAULT_PORT)
    p.add_argument("--token", default=os.environ.get("ROSTER_TOKEN", ""),
                   help="secret required on every route but /health ($ROSTER_TOKEN)")
    p.add_argument("--cors", metavar="ORIGIN", default="",
                   help="allow browser calls from this origin, e.g. http://localhost:5173")
    p.add_argument("--ui", metavar="DIR", help="serve this folder as the questionnaire")
    p.add_argument("--max-body", type=int, default=api.MAX_BODY_BYTES,
                   help="largest request body accepted, in bytes")
    p.add_argument("--max-searches", type=int, default=2,
                   help="solves allowed at once; further ones get 429")
    p.add_argument("--insecure", action="store_true",
                   help="permit a non-loopback bind with no token")
    p.add_argument("-q", "--quiet", action="store_true", help="do not log requests")
    p.add_argument("--fastapi", action="store_true",
                   help="serve through FastAPI and uvicorn instead, if installed")
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ServiceError as exc:
        print(f"error: {exc.message}" + (f" (field {exc.field})" if exc.field else ""),
              file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
