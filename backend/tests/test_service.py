"""The JSON boundary: what the HTTP layer will pass in and hand back."""

from __future__ import annotations

import json
import unittest

from roster.generate import small_instance, university_instance
from roster.service import (
    ENDPOINTS, MAX_SECONDS_CAP, ServiceError, evaluate_payload, handle,
    repair_payload, schema_payload, solve_payload, validate_payload,
)


FAST = {"seed": 7, "max_seconds": 60.0, "max_iterations": 3000,
        "iterations_per_level": 200, "polish_iterations": 0}


def payload(inst=None, **extra) -> dict:
    body = {"instance": (inst or small_instance()).to_dict(), "options": dict(FAST)}
    body.update(extra)
    return body


class TestSolveEndpoint(unittest.TestCase):
    def setUp(self):
        self.out = solve_payload(payload())

    def test_response_carries_every_section_the_ui_needs(self):
        self.assertEqual(
            set(self.out),
            {"instance", "roster", "score", "coverage", "workload", "spread",
             "violations_by_employee", "rules", "search"},
        )

    def test_the_roster_has_one_row_per_employee_and_one_cell_per_day(self):
        inst_out, roster = self.out["instance"], self.out["roster"]
        self.assertEqual(len(roster["rows"]), inst_out["employees"])
        self.assertEqual(len(roster["dates"]), inst_out["num_days"])
        for row in roster["rows"]:
            self.assertEqual(len(row["days"]), inst_out["num_days"])

    def test_the_search_block_says_what_engine_ran(self):
        search = self.out["search"]
        self.assertEqual(search["engine"], "construct+anneal")
        self.assertEqual(search["options"]["seed"], 7)
        self.assertGreater(search["iterations"], 0)
        self.assertLessEqual(search["cost"], search["construction_cost"] + 1e-6)

    def test_the_score_is_internally_consistent(self):
        score = self.out["score"]
        self.assertAlmostEqual(score["cost"], score["hard_cost"] + score["soft_cost"],
                               places=3)
        self.assertEqual(score["feasible"], score["hard_violations"] == 0)
        self.assertAlmostEqual(sum(score["by_rule"].values()), score["cost"], places=2)

    def test_the_whole_response_survives_json(self):
        text = json.dumps(self.out)
        self.assertEqual(json.loads(text)["score"]["cost"], self.out["score"]["cost"])

    def test_history_is_opt_in(self):
        self.assertNotIn("history", self.out["search"])
        with_history = solve_payload(payload(include_history=True))
        self.assertTrue(with_history["search"]["history"])

    def test_a_bare_instance_body_is_accepted_without_the_wrapper(self):
        body = small_instance().to_dict()
        body["options"] = dict(FAST)
        out = solve_payload(body)
        self.assertIn("roster", out)


class TestEvaluateEndpoint(unittest.TestCase):
    def setUp(self):
        self.inst = small_instance()
        self.solved = solve_payload(payload(self.inst))

    def test_evaluating_the_solver_s_own_roster_reproduces_its_score(self):
        out = evaluate_payload(payload(self.inst, roster=self.solved["roster"]))
        self.assertAlmostEqual(out["score"]["cost"], self.solved["score"]["cost"],
                               places=3)
        self.assertEqual(out["score"]["by_rule"], self.solved["score"]["by_rule"])

    def test_evaluate_leaves_the_roster_alone(self):
        out = evaluate_payload(payload(self.inst, roster=self.solved["roster"]))
        self.assertEqual(out["roster"], self.solved["roster"])

    def test_an_empty_roster_is_scored_as_wholly_uncovered(self):
        blank = {"dates": self.solved["roster"]["dates"],
                 "rows": [{"employee": row["employee"],
                           "days": [None] * self.inst.num_days}
                          for row in self.solved["roster"]["rows"]]}
        out = evaluate_payload(payload(self.inst, roster=blank))
        self.assertEqual(out["coverage"]["under"], self.inst.total_required)
        self.assertFalse(out["score"]["feasible"])

    def test_violations_are_grouped_by_person(self):
        out = evaluate_payload(payload(self.inst, roster=self.solved["roster"]))
        ids = {row["employee"] for row in self.solved["roster"]["rows"]}
        for who in out["violations_by_employee"]:
            self.assertTrue(who in ids or who == "",
                            f"unexpected violation owner {who!r}")


class TestRepairEndpoint(unittest.TestCase):
    def test_repair_reports_where_it_started_and_does_not_end_worse(self):
        inst = small_instance()
        blank = {"dates": [], "rows": [{"employee": e.id, "days": [None] * inst.num_days}
                                       for e in inst.employees]}
        out = repair_payload(payload(inst, roster=blank))
        self.assertEqual(out["search"]["engine"], "repair")
        self.assertGreater(out["before"]["cost"], out["score"]["cost"])
        self.assertGreater(out["before"]["hard_violations"], 0)

    def test_repair_keeps_manual_decisions_that_no_rule_objects_to(self):
        inst = small_instance()
        dates = [d.iso for d in inst.horizon.days]
        rows = [{"employee": e.id, "days": [None] * inst.num_days}
                for e in inst.employees]
        keeper = inst.employees[0]
        rows[0]["days"][0] = {"shift": inst.shifts[0].id, "role": keeper.roles[0]}
        out = repair_payload(payload(inst, roster={"dates": dates, "rows": rows}))
        got = next(r for r in out["roster"]["rows"] if r["employee"] == keeper.id)
        self.assertIsNotNone(got["days"][0])


class TestSchemaEndpoint(unittest.TestCase):
    def test_schema_needs_no_instance(self):
        out = schema_payload()
        self.assertEqual(out["severities"], ["hard", "soft"])
        self.assertEqual(out["rule_type_count"], len(out["rule_types"]))
        self.assertGreaterEqual(out["rule_type_count"], 24)

    def test_every_rule_type_arrives_with_its_parameters(self):
        for entry in schema_payload()["rule_types"]:
            self.assertIn("type", entry)
            self.assertIn("params", entry)
            self.assertIn(entry["default_severity"], ("hard", "soft"), entry["type"])
            self.assertIn(entry["applies_to"], ("row", "coverage", "global"),
                          entry["type"])

    def test_an_instance_fills_in_the_dropdown_choices(self):
        out = schema_payload({"instance": small_instance().to_dict()})
        blob = json.dumps(out)
        self.assertIn("DSG", blob)
        self.assertTrue(out["scope"]["roles"])
        self.assertTrue(out["scope"]["employees"])


class TestValidateEndpoint(unittest.TestCase):
    def test_a_workable_instance_passes(self):
        out = validate_payload(payload(university_instance(num_days=14,
                                                           num_employees=40)))
        self.assertTrue(out["ok"], out["problems"])
        self.assertEqual(out["problems"], [])
        self.assertEqual(out["instance"]["num_days"], 14)
        self.assertEqual(out["instance"]["employees"], 40)

    def test_impossible_demand_is_named_rather_than_left_to_the_solver(self):
        inst = university_instance(num_days=14, num_employees=6)
        out = validate_payload(payload(inst))
        self.assertFalse(out["ok"])
        self.assertTrue(any("qualified staff" in p or "nobody holds it" in p
                            for p in out["problems"]), out["problems"])

    def test_capacity_is_broken_down_by_role(self):
        inst = university_instance(num_days=14, num_employees=40)
        out = validate_payload(payload(inst))
        for role, cap in out["capacity_by_role"].items():
            self.assertGreaterEqual(cap["person_days_available"],
                                    cap["person_days_demanded"], role)

    def test_rules_come_back_described_in_words(self):
        out = validate_payload(payload(small_instance()))
        self.assertTrue(all(line.startswith(("[hard]", "[soft]"))
                            for line in out["rules"]))


class TestRejections(unittest.TestCase):
    def assert_error(self, fn, body, field="", pattern=""):
        with self.assertRaises(ServiceError) as caught:
            fn(body)
        err = caught.exception
        if field:
            self.assertEqual(err.field, field)
        if pattern:
            self.assertIn(pattern, err.message)
        self.assertEqual(set(err.to_dict()), {"error", "field"})
        return err

    def test_body_must_be_an_object(self):
        self.assert_error(solve_payload, ["not", "a", "dict"])

    def test_instance_must_be_an_object(self):
        self.assert_error(solve_payload, {"instance": "employees please"},
                          field="instance")

    def test_a_broken_instance_is_reported_against_the_instance_field(self):
        bad = small_instance().to_dict()
        bad["employees"][0]["roles"] = ["NOT_A_ROLE"]
        self.assert_error(solve_payload, {"instance": bad}, field="instance",
                          pattern="instance rejected")

    def test_unknown_solver_options_are_refused(self):
        self.assert_error(solve_payload,
                          payload(options={"turbo": True}), field="options")

    def test_options_must_be_an_object(self):
        self.assert_error(solve_payload, payload(options=[1, 2]), field="options")

    def test_an_option_of_the_wrong_type_names_the_option(self):
        self.assert_error(solve_payload, payload(options={"seed": "soon"}),
                          field="options.seed")

    def test_the_time_budget_is_capped(self):
        self.assert_error(solve_payload,
                          payload(options={"max_seconds": MAX_SECONDS_CAP + 1}),
                          field="options.max_seconds")
        self.assert_error(solve_payload, payload(options={"max_seconds": 0}),
                          field="options.max_seconds")

    def test_hard_weight_must_be_positive(self):
        self.assert_error(solve_payload, payload(options={"hard_weight": 0}),
                          field="options.hard_weight")

    def test_evaluate_needs_a_roster(self):
        self.assert_error(evaluate_payload, payload(), field="roster")

    def test_roster_rows_must_be_a_list(self):
        self.assert_error(evaluate_payload, payload(roster={"rows": "A,B,C"}),
                          field="roster.rows")

    def test_a_roster_row_needs_an_employee_and_days(self):
        self.assert_error(evaluate_payload, payload(roster={"rows": [{"days": []}]}),
                          field="roster.rows.0")

    def test_an_unknown_employee_is_rejected(self):
        inst = small_instance()
        self.assert_error(
            evaluate_payload,
            payload(inst, roster={"rows": [{"employee": "GHOST",
                                            "days": [None] * inst.num_days}]}),
            field="roster.rows.0", pattern="unknown employee")

    def test_a_row_of_the_wrong_length_is_rejected(self):
        inst = small_instance()
        self.assert_error(
            evaluate_payload,
            payload(inst, roster={"rows": [{"employee": inst.employees[0].id,
                                            "days": [None] * 3}]}),
            field="roster.rows.0", pattern="horizon has")

    def test_a_cell_naming_an_unknown_shift_is_rejected(self):
        inst = small_instance()
        days = [None] * inst.num_days
        days[0] = {"shift": "Z", "role": inst.employees[0].roles[0]}
        self.assert_error(
            evaluate_payload,
            payload(inst, roster={"rows": [{"employee": inst.employees[0].id,
                                            "days": days}]}),
            field="roster", pattern="roster rejected")


class TestDispatch(unittest.TestCase):
    def test_handle_routes_by_name(self):
        out = handle("validate", payload())
        self.assertIn("capacity_by_role", out)

    def test_every_endpoint_is_reachable_through_handle(self):
        self.assertEqual(set(ENDPOINTS),
                         {"solve", "evaluate", "repair", "schema", "validate"})
        self.assertIn("rule_types", handle("schema", {}))

    def test_an_unknown_endpoint_lists_the_real_ones(self):
        with self.assertRaises(ServiceError) as caught:
            handle("optimise", payload())
        self.assertIn("unknown endpoint", caught.exception.message)
        self.assertIn("validate", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
