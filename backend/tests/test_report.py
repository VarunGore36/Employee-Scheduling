"""What the admin reads. Every number in the text must match the JSON."""

from __future__ import annotations

import csv
import io
import unittest

from roster import report
from roster.rules import RuleSet
from roster.schema import Demand
from roster.state import RosterState

from .helpers import DSG, LSG, MTS, instance, lay_out, rule


class ReportCase(unittest.TestCase):
    def setUp(self):
        self.inst = instance(days=7, demand=[
            Demand(day=0, shift="M", role=DSG, required=2),
            Demand(day=1, shift="N", role=LSG, required=1),
            Demand(day=5, shift="M", role=DSG, required=1),
        ], rules=[
            rule("under", "coverage", direction="under"),
            rule("over", "coverage", severity="soft", weight=2.0, direction="over"),
            rule("run", "max_consecutive_working_days", max=3),
            rule("fair", "balance_workload", severity="soft", weight=5.0,
                 measure="shifts", tolerance=0),
        ])
        # A: 4 in a row (breaks 'run'), B: a night, C: one weekend morning
        self.state = lay_out(self.inst, {"A": "MMMM...",
                                         "B": ".N.....",
                                         "C": ".....M."})
        self.rules = RuleSet(self.inst)
        self.evaluation = self.rules.evaluate(self.state)


class TestGrid(ReportCase):
    def test_grid_has_three_header_rows_and_one_row_per_employee(self):
        lines = report.roster_grid(self.state).splitlines()
        self.assertEqual(len(lines), 3 + self.inst.num_employees)

    def test_header_shows_day_numbers_weekday_initials_and_weekend_marks(self):
        day_row, dow_row, mark_row = report.roster_grid(self.state).splitlines()[:3]
        self.assertIn("7  8  9 10 11 12 13", day_row)     # 2026-09-07 is a Monday
        self.assertIn("M  T  W  T  F  S  S", dow_row)
        self.assertEqual(mark_row.count("~"), 2)          # Saturday and Sunday

    def test_a_row_shows_the_pattern_and_that_person_s_totals(self):
        row = next(l for l in report.roster_grid(self.state).splitlines()
                   if l.startswith("A "))
        self.assertIn("M  M  M  M  .  .  .", row)
        self.assertIn("   4      0", row)                 # 4 duties, 0 nights
        self.assertTrue(row.rstrip().endswith(DSG))

    def test_days_off_are_marked_with_a_dot(self):
        row = next(l for l in report.roster_grid(self.state).splitlines()
                   if l.startswith("C "))
        self.assertEqual(row.count("."), 6)

    def test_roles_can_be_shown_in_the_cells(self):
        """Worth switching on when staff cross-cover: C works a morning as LSG."""
        grid = report.roster_grid(self.state, show_role=True)
        self.assertIn(f"M/{DSG}", grid)
        self.assertIn(f"M/{LSG}", grid)

    def test_shift_letter_handles_the_off_marker(self):
        self.assertEqual(report.shift_letter(self.inst, -1, -1), report.OFF_MARK)
        self.assertEqual(report.shift_letter(self.inst, 0, 0), "M")


class TestCoverageTable(ReportCase):
    def test_one_line_per_demanded_cell_plus_a_header(self):
        lines = report.coverage_table(self.state).splitlines()
        self.assertEqual(len(lines), 1 + len(self.inst.demand_cells))

    def test_shortfalls_and_surplus_are_flagged(self):
        text = report.coverage_table(self.state)
        self.assertIn("SHORT", text)          # day 0 wants 2 DSG mornings, has 1
        self.assertIn("2026-09-07", text)

    def test_a_satisfied_cell_carries_no_flag(self):
        state = lay_out(self.inst, {"A": "M......", "B": "MN.....", "C": ".....M."})
        line = next(l for l in report.coverage_table(state).splitlines()
                    if "2026-09-07" in l)
        self.assertNotIn("SHORT", line)
        self.assertNotIn("extra", line)


class TestWorkload(ReportCase):
    def test_rows_carry_the_fairness_evidence(self):
        rows = {r["employee"]: r for r in report.workload_rows(self.state)}
        self.assertEqual(rows["A"]["duties"], 4)
        self.assertEqual(rows["A"]["hours"], 32.0)
        self.assertEqual(rows["A"]["longest_run"], 4)
        self.assertEqual(rows["A"]["by_shift"], {"M": 4, "E": 0, "N": 0})
        self.assertEqual(rows["B"]["nights"], 1)
        self.assertEqual(rows["C"]["weekends"], 1)
        self.assertEqual(rows["C"]["roles"], sorted([LSG, MTS]))

    def test_longest_run_is_zero_for_somebody_who_never_works(self):
        state = lay_out(self.inst, {"A": "......."})
        self.assertEqual(report.workload_rows(state)[0]["longest_run"], 0)

    def test_spread_is_max_minus_min_across_staff(self):
        spread = report._spread(self.state)
        self.assertEqual(spread["duties"], 4 - 1)
        self.assertEqual(spread["nights"], 1 - 0)
        self.assertEqual(spread["weekends"], 1 - 0)
        self.assertEqual(spread["hours"], 32.0 - 8.0)

    def test_table_ends_with_the_spread_line(self):
        text = report.workload_table(self.state)
        self.assertIn("spread (max-min): duties 3, nights 1, weekends 1",
                      text.splitlines()[-1])

    def test_table_has_a_line_per_employee_plus_rules_and_a_spread_line(self):
        lines = report.workload_table(self.state).splitlines()
        self.assertEqual(len(lines), 2 + self.inst.num_employees + 2)


class TestViolationViews(ReportCase):
    def test_report_leads_with_the_verdict(self):
        text = report.violation_report(self.evaluation, self.rules)
        self.assertTrue(text.startswith("NOT LEGAL:"))
        self.assertIn("hard and", text)

    def test_hard_rules_are_reported_before_soft_ones(self):
        text = report.violation_report(self.evaluation, self.rules)
        self.assertLess(text.index("Hard rules broken"), text.index("Soft rules bent"))

    def test_the_admin_s_own_label_is_quoted_back(self):
        inst = instance(days=7, rules=[
            rule("run", "max_consecutive_working_days", max=3,
                 label="Nobody does more than three days on the trot")])
        rules = RuleSet(inst)
        state = lay_out(inst, {"A": "MMMM..."})
        text = report.violation_report(rules.evaluate(state), rules)
        self.assertIn("Nobody does more than three days on the trot", text)
        self.assertIn("[run]", text)

    def test_long_lists_are_truncated_but_still_counted(self):
        inst = instance(days=14, rules=[rule("iso", "min_consecutive_working_days", min=2)])
        rules = RuleSet(inst)
        # seven isolated days, but the one on the last day is clipped by the horizon
        state = lay_out(inst, {"A": ".M.M.M.M.M.M.M"})
        text = report.violation_report(rules.evaluate(state), rules, limit_per_rule=2)
        self.assertIn("6 breach(es)", text)
        self.assertIn("and 4 more", text)

    def test_a_clean_roster_says_so_in_one_line(self):
        inst = instance(days=7, rules=[rule("run", "max_consecutive_working_days", max=3)])
        rules = RuleSet(inst)
        clean = rules.evaluate(lay_out(inst, {"A": "MM....."}))
        self.assertEqual(report.violation_report(clean, rules), "No rule was broken.")

    def test_grouping_by_employee_keeps_only_personal_breaches(self):
        grouped = report.violations_by_employee(self.evaluation)
        self.assertIn("A", grouped)
        self.assertEqual(grouped["A"][0]["rule_id"], "run")
        self.assertEqual(grouped["A"][0]["employee"], "A")
        self.assertNotIn("", grouped)          # coverage and fairness are nobody's

    def test_grouped_employees_come_back_sorted(self):
        inst = instance(days=7, rules=[rule("run", "max_consecutive_working_days", max=2)])
        rules = RuleSet(inst)
        state = lay_out(inst, {"A": "MMM....", "B": "MMM....", "C": "MMM...."})
        grouped = report.violations_by_employee(rules.evaluate(state))
        self.assertEqual(list(grouped), ["A", "B", "C"])


class TestCsv(ReportCase):
    def rows(self, text):
        return list(csv.reader(io.StringIO(text)))

    def test_wide_roster_csv_has_a_column_per_day(self):
        rows = self.rows(report.roster_csv(self.state))
        self.assertEqual(len(rows), 1 + self.inst.num_employees)
        # employee, name, roles, 7 dates, duties, nights
        self.assertEqual(len(rows[0]), 3 + self.inst.num_days + 2)
        self.assertEqual(rows[0][3], "2026-09-07")
        self.assertEqual(rows[1][3], f"M/{DSG}")

    def test_wide_csv_leaves_days_off_empty(self):
        rows = self.rows(report.roster_csv(self.state))
        self.assertEqual(rows[1][-3], "")          # A is off on the last day

    def test_long_assignments_csv_has_a_row_per_duty(self):
        rows = self.rows(report.assignments_csv(self.state))
        self.assertEqual(len(rows) - 1, self.state.assignments())
        self.assertEqual(rows[0][:4], ["date", "weekday", "shift", "start"])

    def test_long_csv_carries_the_clock_times(self):
        rows = self.rows(report.assignments_csv(self.state))
        night = next(r for r in rows[1:] if r[2] == "N")
        self.assertEqual(night[3], "22:00")
        self.assertEqual(night[4], "06:00")
        self.assertEqual(night[6], "B")

    def test_long_csv_is_ordered_by_day(self):
        rows = self.rows(report.assignments_csv(self.state))[1:]
        self.assertEqual([r[0] for r in rows], sorted(r[0] for r in rows))

    def test_violations_csv_has_a_row_per_breach(self):
        rows = self.rows(report.violations_csv(self.evaluation))
        self.assertEqual(len(rows) - 1, len(self.evaluation.violations))
        self.assertEqual(rows[0][0], "rule_id")


class TestAssembledViews(ReportCase):
    def test_summary_covers_horizon_staff_demand_verdict_and_fairness(self):
        text = "\n".join(report.summary_lines(self.state, self.evaluation))
        self.assertIn("2026-09-07 for 7 days (2026-09-13 inclusive)", text)
        self.assertIn("3 across 3 roles, 3 shifts a day", text)
        self.assertIn(f"{self.inst.total_required} person-shifts; rostered 6", text)
        self.assertIn("NOT legal", text)
        self.assertIn("duty spread 3", text)

    def test_text_report_includes_the_sections_asked_for_and_no_others(self):
        text = report.text_report(self.state, self.evaluation, self.rules)
        for heading in ("ROSTER", "WORKLOAD", "RULES"):
            self.assertIn(heading, text)
        self.assertNotIn("COVERAGE", text)
        with_cov = report.text_report(self.state, self.evaluation, self.rules,
                                      sections=("coverage",))
        self.assertIn("COVERAGE", with_cov)
        self.assertNotIn("ROSTER", with_cov)

    def test_the_grid_legend_names_every_shift_and_its_clock(self):
        text = report.text_report(self.state, self.evaluation, self.rules,
                                  sections=("grid",))
        self.assertIn("22:00-06:00", text)
        self.assertIn("=off, ~=weekend", text)

    def test_report_dict_has_the_sections_the_frontend_expects(self):
        data = report.report_dict(self.state, self.evaluation, self.rules)
        self.assertEqual(set(data), {"instance", "roster", "score", "coverage",
                                     "workload", "spread", "violations_by_employee",
                                     "rules"})
        self.assertEqual(len(data["rules"]), len(self.inst.rules))

    def test_report_dict_and_the_text_view_agree_on_the_numbers(self):
        data = report.report_dict(self.state, self.evaluation, self.rules)
        self.assertEqual(data["coverage"]["under"], self.state.under_coverage())
        self.assertEqual(data["coverage"]["over"], self.state.over_coverage())
        self.assertEqual(data["spread"], report._spread(self.state))
        self.assertEqual(data["workload"], report.workload_rows(self.state))
        self.assertEqual(data["score"]["cost"], round(self.evaluation.cost, 4))

    def test_coverage_gaps_are_listed_with_dates_and_names(self):
        gap = report.report_dict(self.state, self.evaluation, self.rules)["coverage"]["gaps"]
        first = next(g for g in gap if g["date"] == "2026-09-07")
        self.assertEqual((first["shift"], first["role"]), ("M", DSG))
        self.assertEqual((first["have"], first["required"]), (1, 2))

    def test_report_dict_works_without_a_ruleset(self):
        data = report.report_dict(self.state, self.evaluation)
        self.assertEqual(data["rules"], [])

    def test_report_dict_survives_a_json_round_trip_unchanged(self):
        import json
        data = report.report_dict(self.state, self.evaluation, self.rules)
        self.assertEqual(json.loads(json.dumps(data)), data)


class TestEmptyRoster(unittest.TestCase):
    """Nothing rostered yet is the state the admin starts in; it must render."""

    def setUp(self):
        self.inst = instance(days=5, demand=[
            Demand(day=0, shift="M", role=DSG, required=1)],
            rules=[rule("under", "coverage", direction="under")])
        self.state = RosterState(self.inst)
        self.rules = RuleSet(self.inst)
        self.evaluation = self.rules.evaluate(self.state)

    def test_every_view_renders(self):
        for text in (report.roster_grid(self.state),
                     report.coverage_table(self.state),
                     report.workload_table(self.state),
                     report.violation_report(self.evaluation, self.rules),
                     report.text_report(self.state, self.evaluation, self.rules)):
            self.assertTrue(text.strip())

    def test_spread_is_zero_when_nobody_works(self):
        self.assertEqual(report._spread(self.state),
                         {"duties": 0, "nights": 0, "weekends": 0, "hours": 0})

    def test_the_long_csv_is_just_its_header(self):
        self.assertEqual(len(report.assignments_csv(self.state).splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
