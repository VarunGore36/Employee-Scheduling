"""Rule catalogue for the frontend."""

from __future__ import annotations

from .rules import REGISTRY, ROLE, SHIFT, SHIFTS
from .schema import HARD, SCOPE_KINDS, Instance


def catalog(inst: Instance | None = None) -> list[dict]:
    """Every registered rule type as a form descriptor."""
    out = []
    for type_name in sorted(REGISTRY):
        cls = REGISTRY[type_name]
        params = []
        for spec in cls.params_spec:
            field = dict(spec)
            if inst is not None:
                if field["kind"] in (SHIFT, SHIFTS):
                    field["options"] = [s.id for s in inst.shifts]
                elif field["kind"] == ROLE:
                    field["options"] = [r.id for r in inst.roles]
            params.append(field)
        out.append({
            "type": type_name,
            "label": cls.label or type_name,
            "help": cls.help,
            "example": cls.example,
            "applies_to": cls.eval_kind,
            "default_severity": getattr(cls, "default_severity", HARD),
            "params": params,
        })
    return out


def scope_options(inst: Instance | None = None) -> dict:
    """Choices for the 'who does this apply to?' part of the form."""
    out: dict = {"kinds": list(SCOPE_KINDS)}
    if inst is not None:
        out["employees"] = [
            {"id": e.id, "name": e.name or e.id} for e in inst.employees
        ]
        out["roles"] = [r.id for r in inst.roles]
        out["contracts"] = sorted({e.contract for e in inst.employees if e.contract})
    return out


def form_schema(inst: Instance | None = None) -> dict:
    """One payload the frontend can fetch to build the whole questionnaire."""
    return {
        "rule_types": catalog(inst),
        "scope": scope_options(inst),
        "severities": ["hard", "soft"],
        "notes": (
            "Hard rules must hold for the roster to be valid; soft rules are "
            "traded off against each other by weight. Weight is ignored for "
            "hard rules unless you want one hard rule prioritised over another "
            "when no fully legal roster exists."
        ),
    }
