"""Rules written as prose: what the parser may conclude, and what it must refuse."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace

from roster.generate import university_instance
from roster.parse import (
    Parser, bound_for, fold_numbers, label_of, normalise, parse, parse_payload,
    rewrite_comparatives, severity_of, split_compound, split_statements, statements,
    subject_of, weight_of,
)
from roster.rules import REGISTRY, RuleSet
from roster.schema import HARD, SOFT, Instance, Rule

# 2026-09-12 to 2026-10-12, 44 staff as E01..E44, shifts M/E/N, roles DSG/LSG/MTS.
INST = university_instance()


def only(text: str, inst: Instance | None = INST):
    """The single draft one statement must produce."""
    found = parse(text, inst)
    if len(found) != 1:
        raise AssertionError(f"{len(found)} drafts for {text!r}")
    return found[0]


def read(text: str, inst: Instance | None = INST) -> tuple[str, dict]:
    """``(rule type, params)`` for a statement that has to be readable."""
    draft = only(text, inst)
    if not draft.ok:
        raise AssertionError(f"{text!r} was not read: {draft.problem}")
    return draft.rule["type"], draft.rule["params"]


def refused(text: str, inst: Instance | None = INST) -> str:
    """The problem reported for a statement that has to be refused."""
    draft = only(text, inst)
    if draft.ok:
        raise AssertionError(f"{text!r} became {draft.rule['type']} {draft.rule['params']}")
    return draft.problem


class TestReadingTheWords(unittest.TestCase):
    """Splitting, tidying and number words, before any rule is chosen."""

    def test_one_line_may_hold_several_statements(self):
        self.assertEqual(
            statements("a\nb; c\n\n   \nd. e\n"),
            [(1, "a"), (2, "b"), (2, "c"), (5, "d"), (5, "e")])

    def test_a_dotted_date_does_not_end_a_statement(self):
        self.assertEqual(split_statements("Leave on 23.09.2026. Fine."),
                         ["Leave on 23.09.2026. Fine"])

    def test_bullets_and_numbering_are_not_part_of_the_rule(self):
        self.assertEqual(label_of("  1. Nobody may work 6 days in a row.  "),
                         "Nobody may work 6 days in a row")
        self.assertEqual(normalise("- No-one may work SIX days"),
                         "nobody may work 6 days")

    def test_number_words_become_digits(self):
        self.assertEqual(fold_numbers("no more than six days"), "no more than 6 days")
        self.assertEqual(fold_numbers("twenty two duties"), "22 duties")

    def test_an_article_counts_one_but_a_rate_is_left_alone(self):
        self.assertEqual(fold_numbers("give a day off"), "give 1 day off")
        self.assertEqual(fold_numbers("8 hours a day"), "8 hours a day")

    def test_comparatives_become_the_bounds_the_patterns_expect(self):
        for text, want in (("not more than 48 hrs a week", "at most 48 hrs a week"),
                           ("6 or fewer weekends", "at most 6 weekends"),
                           ("3 or more people", "at least 3 people"),
                           ("keep staff to 3 weekends", "staff at most 3 weekends"),
                           ("no employee may work more than 6 days",
                            "employee may work at most 6 days"),
                           ("no shift longer than 12 hours",
                            "shift at most 12 hours")):
            self.assertEqual(rewrite_comparatives(normalise(text))[0], want, text)

    def test_the_subject_a_negative_governs_is_kept_when_the_bound_is_rewritten(self):
        problem = refused("No shift longer than 12 hours.")
        self.assertIn("how long a shift is", problem)
        self.assertEqual(read("No week higher than 48 hours."),
                         ("hours_per_window", {"max_hours": 48}))

    def test_more_than_without_a_prohibition_is_read_as_a_floor_and_said_so(self):
        out, notes = rewrite_comparatives(normalise("everyone works more than 8 duties"))
        self.assertEqual(out, "everyone works at least 9 duties")
        self.assertTrue(any("floor one higher" in note for note in notes), notes)

    def test_a_bound_is_found_even_when_it_trails_its_subject(self):
        self.assertEqual(bound_for("at least 12 days off a month", "days off"),
                         (12, None))
        self.assertEqual(
            bound_for("total working days in a month must be at least 12", "days"),
            (12, None))
        self.assertIsNone(bound_for("at least 12 hours of rest", "weekends"))

    def test_a_limit_word_left_at_the_end_still_governs_its_number(self):
        for text, want in (("days in a row: 6 at most", "days in a row: at most 6"),
                           ("nights: 4 maximum", "nights: at most 4"),
                           ("weekly hours: 48 max", "weekly hours: at most 48"),
                           ("duties: 8 minimum", "duties: at least 8")):
            self.assertEqual(rewrite_comparatives(normalise(text))[0], want, text)

    def test_a_number_a_limit_word_governs_elsewhere_is_left_alone(self):
        for text in ("shift 2 minimum 3 people", "between 4 and 6 nights maximum",
                     "at most 6 days in a row"):
            self.assertNotIn("at most 2", rewrite_comparatives(normalise(text))[0], text)
            self.assertNotIn("at least 2", rewrite_comparatives(normalise(text))[0], text)

    def test_the_subject_of_a_bound_is_what_the_bound_counts(self):
        self.assertEqual(subject_of("at least 2 people on every night shift"), "people")
        self.assertEqual(subject_of("at least 1 day off a week"), "days off")
        self.assertEqual(subject_of("at most 4 nights in the month"), "nights")


class TestHowBindingItIs(unittest.TestCase):
    """Severity and weight come from the admin's own wording."""

    def severity(self, text: str) -> str:
        return severity_of(normalise(text))[0]

    def test_must_and_its_relatives_are_hard(self):
        for text in ("staff must not work 7 days", "a weekly off is mandatory",
                     "nights may not exceed 8", "never fewer than 3 at night"):
            self.assertEqual(self.severity(text), HARD, text)

    def test_should_and_its_relatives_are_soft(self):
        for text in ("staff should get 2 days off", "try to give weekends off",
                     "days off preferably come in pairs", "avoid isolated days"):
            self.assertEqual(self.severity(text), SOFT, text)

    def test_should_says_why_it_was_read_as_a_preference(self):
        self.assertIn("say 'must' if it is binding",
                      severity_of(normalise("staff should get 2 days off"))[1])

    def test_nobody_is_hard_but_preferably_nobody_is_not(self):
        self.assertEqual(self.severity("nobody works more than 6 days in a row"), HARD)
        self.assertEqual(self.severity("preferably nobody works 7 days"), SOFT)

    def test_wording_that_says_nothing_leaves_severity_to_the_rule_type(self):
        self.assertEqual(self.severity("between 8 and 22 duties in the month"), "")
        draft = only("Between 8 and 22 duties in the month.")
        self.assertEqual(draft.rule["severity"], HARD)
        self.assertTrue(any("usual severity" in note for note in draft.assumptions))
        self.assertEqual(only("Share night duty evenly.").rule["severity"], SOFT)

    def test_priority_wording_sets_the_weight(self):
        self.assertEqual(weight_of(normalise("this is critical: 3 at night"))[0], 5.0)
        self.assertEqual(weight_of(normalise("if convenient, share nights"))[0], 0.5)
        self.assertEqual(weight_of(normalise("share nights evenly"))[0], 1.0)
        self.assertEqual(only("This is critical: never fewer than 3 people at night.")
                         .rule["weight"], 5.0)


class TestWhoTheRuleCovers(unittest.TestCase):
    """Scope is read from the names in the statement, or it is everyone."""

    def scope(self, text: str) -> dict:
        return only(text).rule["scope"]

    def test_a_staff_number_names_that_employee(self):
        self.assertEqual(self.scope("Staff 09 must not be rostered on 20 September."),
                         {"kind": "employees", "ids": ["E09"]})

    def test_two_people_in_one_statement_are_both_covered(self):
        self.assertEqual(self.scope("Staff 07 and Staff 09 are on leave on 20 September."),
                         {"kind": "employees", "ids": ["E07", "E09"]})

    def test_a_role_name_scopes_the_rule_to_that_role(self):
        self.assertEqual(self.scope("DSG staff may not work more than 5 days in a row."),
                         {"kind": "roles", "ids": ["DSG"]})

    def test_a_contract_type_scopes_the_rule_to_that_group(self):
        self.assertEqual(
            self.scope("Permanent staff must do at least 10 duties in the month."),
            {"kind": "contracts", "ids": ["permanent"]})

    def test_the_office_words_for_a_contract_hand_reach_the_contract_type(self):
        for text in ("Casual staff are capped at 12 shifts.",
                     "Adhoc staff are capped at 12 shifts.",
                     "Outsourced staff are capped at 12 shifts."):
            self.assertEqual(self.scope(text),
                             {"kind": "contracts", "ids": ["contract"]}, text)

    def test_a_group_named_by_its_pay_is_refused_rather_than_guessed_at(self):
        self.assertIn("pay is outside the roster",
                      refused("Daily wage staff are capped at 12 shifts."))

    def test_a_group_word_no_staff_record_carries_is_refused_not_widened(self):
        only_permanent = replace(
            INST, employees=[replace(one, contract="permanent") for one in INST.employees])
        problem = refused("Casual staff are capped at 12 shifts.", only_permanent)
        self.assertIn("no 'casual' group", problem)
        self.assertIn("contract type", problem)

    def test_naming_nobody_means_everybody(self):
        self.assertEqual(self.scope("Nobody may work more than 6 days in a row."), {})

    def test_a_scope_on_a_coverage_rule_is_dropped_and_said_so(self):
        draft = only("DSG staff: never fewer than 3 people on site at night.")
        self.assertEqual(draft.rule["scope"], {})
        self.assertTrue(any("scope was dropped" in note for note in draft.assumptions),
                        draft.assumptions)

    def test_a_group_the_staff_data_does_not_have_is_refused(self):
        problem = refused("Part time staff should not do nights.")
        self.assertIn("no 'part time' group", problem)
        self.assertIn("contract type", problem)

    def test_scoping_by_a_personal_attribute_is_refused(self):
        for text in ("Women must not be given night duty.",
                     "The senior most staff get first choice.",
                     "New joiners should not be given nights."):
            self.assertIn("cannot be scoped", refused(text), text)


class TestDates(unittest.TestCase):
    """Every date form an Indian roster office actually writes."""

    def days(self, text: str) -> list[str]:
        return only(text).rule["params"]["days"]

    def test_an_iso_date(self):
        self.assertEqual(read("Staff 13 wants the evening shift on 2026-09-25.")[1],
                         {"day": "2026-09-25", "shift": "E"})

    def test_day_first_numeric_dates_with_slashes_and_dots(self):
        self.assertEqual(self.days("Staff 12 has applied for leave on 18/09/2026."),
                         ["2026-09-18"])
        self.assertEqual(read("Staff 16 must do the night shift on 23.09.2026.")[1],
                         {"day": "2026-09-23", "shift": "N"})

    def test_a_day_and_month_in_words(self):
        self.assertEqual(self.days("Staff 07 is on leave on 15 September."),
                         ["2026-09-15"])

    def test_a_bare_ordinal_lands_in_the_roster_period(self):
        self.assertEqual(self.days("Staff 09 has requested the 20th off."),
                         ["2026-09-20"])

    def test_a_range_becomes_every_day_in_it_and_says_so(self):
        draft = only("Staff 07 is on leave from 15 September to 19 September.")
        self.assertEqual(draft.rule["params"]["days"],
                         ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
                          "2026-09-19"])
        self.assertTrue(any("every day from" in note for note in draft.assumptions))

    def test_a_length_from_a_start_becomes_that_many_days(self):
        draft = only("Staff 15 is on leave for 4 days from the 22nd.")
        self.assertEqual(draft.rule["params"]["days"],
                         ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"])
        self.assertTrue(any("4 days from" in note for note in draft.assumptions))

    def test_and_lists_dates_rather_than_bracketing_a_range(self):
        self.assertEqual(self.days("Staff 09 is on leave on the 1st and the 15th."),
                         ["2026-09-15", "2026-10-01"])

    def test_a_weekday_name_becomes_every_such_day_in_the_period(self):
        draft = only("Contract staff cannot work Sundays.")
        self.assertEqual(draft.rule["params"]["days"],
                         ["2026-09-13", "2026-09-20", "2026-09-27", "2026-10-04",
                          "2026-10-11"])
        self.assertTrue(any("every Sunday" in note for note in draft.assumptions))

    def test_a_date_outside_the_roster_period_is_refused_by_date(self):
        self.assertIn("2026-12-05 is outside the horizon",
                      refused("Staff 07 is on leave on 5 December."))


class TestLimitsOnOnePerson(unittest.TestCase):
    """The row rules: what one person's month may look like."""

    def test_a_run_of_working_days(self):
        self.assertEqual(read("Nobody may work more than 6 days in a row."),
                         ("max_consecutive_working_days", {"max": 6}))
        self.assertEqual(read("Staff must not be rostered for more than six "
                              "consecutive days."),
                         ("max_consecutive_working_days", {"max": 6}))

    def test_a_lone_working_day_becomes_a_floor_on_the_run(self):
        draft = only("Avoid isolated single working days.")
        self.assertEqual((draft.rule["type"], draft.rule["params"]),
                         ("min_consecutive_working_days", {"min": 2}))
        self.assertTrue(any("lone working day" in note for note in draft.assumptions))

    def test_days_off_in_pairs(self):
        draft = only("Days off should preferably come in pairs.")
        self.assertEqual((draft.rule["type"], draft.rule["params"]),
                         ("min_consecutive_days_off", {"min": 2}))
        self.assertEqual(read("There should be a break of at least 2 days after 6 "
                              "continuous days.")[0], "min_consecutive_days_off")

    def test_rest_between_two_duties(self):
        self.assertEqual(read("There must be at least 12 hours of rest between two "
                              "duties."), ("min_rest_hours", {"hours": 12}))
        self.assertEqual(read("Minimum 12 hrs gap is compulsory between two duties."),
                         ("min_rest_hours", {"hours": 12}))

    def test_a_run_of_one_shift_type(self):
        self.assertEqual(read("No more than 3 nights in a row."),
                         ("max_consecutive_same_shift", {"max": 3, "shift": "N"}))
        self.assertEqual(read("Not more than 3 night shifts at a stretch."),
                         ("max_consecutive_same_shift", {"max": 3, "shift": "N"}))

    def test_days_off_in_a_week(self):
        self.assertEqual(read("Everyone should get at least one weekly off."),
                         ("min_days_off_per_window", {"min": 1, "window": "calendar"}))
        self.assertEqual(read("A minimum of 2 days off per week is desirable."),
                         ("min_days_off_per_window", {"min": 2, "window": "calendar"}))

    def test_a_bare_weekly_off_is_read_as_one_day_and_said_so(self):
        draft = only("Weekly off is mandatory for all.")
        self.assertEqual(draft.rule["params"], {"min": 1, "window": "calendar"})
        self.assertTrue(any("no number was given" in note
                            for note in draft.assumptions), draft.assumptions)


    def test_working_days_in_a_week(self):
        self.assertEqual(read("At most 6 working days in a week."),
                         ("max_working_days_per_window",
                          {"max": 6, "window": "calendar"}))

    def test_duties_in_a_week_are_working_days_in_a_week_and_say_so(self):
        draft = only("No more than 5 duties a week.")
        self.assertEqual((draft.rule["type"], draft.rule["params"]),
                         ("max_working_days_per_window",
                          {"max": 5, "window": "calendar"}))
        self.assertTrue(any("one duty a day" in note for note in draft.assumptions),
                        draft.assumptions)
        self.assertEqual(read("Up to 5 shifts a week.")[1],
                         {"max": 5, "window": "calendar"})

    def test_a_floor_beside_the_ceiling_on_a_week_keeps_the_ceiling_and_says_so(self):
        draft = only("Between 4 and 6 duties a week.")
        self.assertEqual(draft.rule["params"], {"max": 6, "window": "calendar"})
        self.assertTrue(any("only the ceiling was taken" in note
                            for note in draft.assumptions), draft.assumptions)

    def test_the_ceiling_reads_however_the_office_words_it(self):
        for text in ("No higher than 48 hours a week.",
                     "Not greater than 48 hours a week.",
                     "Weekly hours are not to go beyond 48.",
                     "Nobody above 48 hours a week.",
                     "Cap weekly hours at 48.",
                     "Weekly hours: 48 max."):
            self.assertEqual(read(text), ("hours_per_window", {"max_hours": 48}), text)

    def test_a_ban_on_the_whole_week_becomes_six_days_and_says_so(self):
        draft = only("No employee shall work all seven days of a week.")
        self.assertEqual((draft.rule["type"], draft.rule["params"]),
                         ("max_working_days_per_window",
                          {"max": 6, "window": "calendar"}))
        self.assertTrue(any("whole week" in note for note in draft.assumptions))

    def test_hours_in_a_week_calendar_and_rolling(self):
        self.assertEqual(read("Nobody may be rostered more than 48 hours in a week."),
                         ("hours_per_window", {"max_hours": 48}))
        self.assertEqual(read("Maximum 48 hrs in any 7 days."),
                         ("hours_per_window",
                          {"max_hours": 48, "window": "rolling", "window_days": 7}))

    def test_a_rolling_week_reads_however_the_office_words_the_window(self):
        rolling = {"max_hours": 48, "window": "rolling", "window_days": 7}
        for text in ("No one may work more than 48 hours in any 7 day window.",
                     "Cap hours at 48 in any 7-day period.",
                     "Not more than 48 hours in any window of 7 days.",
                     "At most 48 hours within any 7 days.",
                     "48 hours is the ceiling in any 7 day stretch."):
            self.assertEqual(read(text), ("hours_per_window", rolling), text)
        self.assertEqual(read("Maximum 5 duties in any window of 7 days."),
                         ("max_working_days_per_window",
                          {"max": 5, "window": "rolling", "window_days": 7}))

    def test_a_floor_on_hours_for_one_role(self):
        draft = only("MTS staff should get at least 45 hours a week.")
        self.assertEqual((draft.rule["type"], draft.rule["params"]),
                         ("hours_per_window", {"min_hours": 45}))
        self.assertEqual(draft.rule["scope"], {"kind": "roles", "ids": ["MTS"]})

    def test_duties_in_the_month(self):
        self.assertEqual(read("Between 8 and 22 duties in the month."),
                         ("total_shifts_range", {"min": 8, "max": 22}))
        self.assertEqual(read("Each employee should do 8 to 22 duties in the roster "
                              "period."), ("total_shifts_range", {"min": 8, "max": 22}))
        self.assertEqual(read("Total working days in a month must be at least 12."),
                         ("total_shifts_range", {"min": 12}))

    def test_hours_in_the_month(self):
        self.assertEqual(read("Nobody may work more than 180 hours in the month."),
                         ("total_hours_range", {"max_hours": 180}))

    def test_nights_in_the_month(self):
        self.assertEqual(read("At most 8 night duties a month."),
                         ("max_night_shifts", {"max": 8}))

    def test_a_floor_on_nights_needs_the_range_rule_instead(self):
        self.assertEqual(read("Give at most 4 nights and at least 1 night to everyone."),
                         ("shift_type_count_range",
                          {"shift": "N", "min": 1, "max": 4}))

    def test_weekends_worked(self):
        self.assertEqual(read("Try to keep staff to 3 weekends or fewer."),
                         ("max_weekends_worked", {"max": 3}))
        self.assertEqual(read("Prefer whole weekends worked rather than single days."),
                         ("complete_weekends", {}))

    def test_a_forbidden_succession_in_either_wording(self):
        self.assertEqual(read("A night shift must not be followed by a morning shift."),
                         ("forbidden_shift_sequence", {"from": ["N"], "to": ["M"]}))
        draft = only("No morning duty after a night duty.")
        self.assertEqual(draft.rule["params"], {"from": ["N"], "to": ["M"]})
        self.assertTrue(any("reverses the order" in note for note in draft.assumptions))


class TestLimitsAcrossTheRoster(unittest.TestCase):
    """Coverage, headcount and fairness: the rules that look at a whole day or month."""

    def test_coverage_in_both_directions(self):
        self.assertEqual(read("Every duty must be staffed."),
                         ("coverage", {"direction": "under"}))
        self.assertEqual(read("Avoid rostering more people than needed."),
                         ("coverage", {"direction": "over"}))

    def test_a_floor_on_heads_at_night(self):
        self.assertEqual(read("Never fewer than 3 people on site at night."),
                         ("headcount_per_shift", {"shift": "N", "min": 3}))
        self.assertEqual(read("At least 3 hands must be present on the night shift at "
                              "all times."),
                         ("headcount_per_shift", {"shift": "N", "min": 3}))

    def test_a_headcount_with_no_shift_named_is_drafted_once_per_shift(self):
        found = parse("There must be at least 4 people on duty every day.", INST)
        self.assertEqual([d.rule["params"]["shift"] for d in found], ["M", "E", "N"])
        self.assertTrue(all(d.rule["params"]["min"] == 4 for d in found))
        self.assertTrue(any("once for every shift" in note
                            for note in found[0].assumptions), found[0].assumptions)

    def test_fairness_by_what_is_being_shared(self):
        self.assertEqual(read("Share night duty evenly."),
                         ("balance_workload", {"measure": "nights"}))
        self.assertEqual(read("Share weekend duty evenly."),
                         ("balance_workload", {"measure": "weekends"}))
        self.assertEqual(read("Every roster must be fair to all."),
                         ("balance_workload", {"measure": "shifts"}))

    def test_a_stated_spread_becomes_the_tolerance(self):
        self.assertEqual(
            read("Spread total duties evenly across staff, within 2 shifts of each other."),
            ("balance_workload", {"measure": "shifts", "tolerance": 2}))


class TestOnePersonsOwnCircumstances(unittest.TestCase):
    """Leave, requests, preferences and duties already promised."""

    def test_leave_makes_the_person_unavailable(self):
        draft = only("Staff 07 is on leave from 15 September to 19 September.")
        self.assertEqual(draft.rule["type"], "unavailable")
        self.assertEqual(draft.rule["severity"], HARD)
        self.assertEqual(draft.rule["scope"], {"kind": "employees", "ids": ["E07"]})

    def test_a_holiday_for_everyone_is_unavailability_for_everyone(self):
        draft = only("Nobody is to be rostered on 2 October, it is a holiday.")
        self.assertEqual((draft.rule["type"], draft.rule["params"]),
                         ("unavailable", {"days": ["2026-10-02"]}))
        self.assertEqual(draft.rule["scope"], {})

    def test_a_day_off_asked_for_is_a_request_not_a_bar(self):
        draft = only("Staff 09 has requested the 20th off.")
        self.assertEqual(draft.rule["type"], "day_off_request")
        self.assertEqual(draft.rule["severity"], SOFT)

    def test_a_shift_asked_for_and_a_shift_avoided(self):
        self.assertEqual(read("Staff 13 wants the evening shift on 2026-09-25.")[0],
                         "shift_request")
        self.assertEqual(read("Staff 11 would rather avoid night duty."),
                         ("shift_preference", {"shift": "N", "direction": "avoid"}))
        self.assertEqual(read("Staff 17 prefers mornings."),
                         ("shift_preference", {"shift": "M", "direction": "prefer"}))

    def test_a_duty_already_promised_is_fixed(self):
        draft = only("Staff 03 is already committed to the morning shift on 16 September.")
        self.assertEqual((draft.rule["type"], draft.rule["params"]),
                         ("fixed_assignment", {"day": "2026-09-16", "shift": "M"}))
        self.assertEqual(draft.rule["scope"], {"kind": "employees", "ids": ["E03"]})


class TestTwoLimitsInOneSentence(unittest.TestCase):
    """A line that sets two different limits has to become two rules."""

    def test_a_run_and_a_weekly_limit_come_apart(self):
        found = parse("Nobody may work more than 6 days in a row and no more than "
                      "48 hours a week.", INST)
        self.assertEqual([(d.rule["type"], d.rule["params"]) for d in found],
                         [("max_consecutive_working_days", {"max": 6}),
                          ("hours_per_window", {"max_hours": 48})])
        self.assertTrue(all(any("two separate limits" in note for note in d.assumptions)
                            for d in found))

    def test_three_limits_come_apart_into_three(self):
        found = parse("At most 6 days in a row, at least 1 day off a week and no more "
                      "than 40 hours a week.", INST)
        self.assertEqual([d.rule["type"] for d in found],
                         ["max_consecutive_working_days", "min_days_off_per_window",
                          "hours_per_window"])

    def test_a_second_limit_may_borrow_the_first_ones_words(self):
        found = parse("Max 4 nights and 2 weekends in the month.", INST)
        self.assertEqual([(d.rule["type"], d.rule["params"]) for d in found],
                         [("max_night_shifts", {"max": 4}),
                          ("max_weekends_worked", {"max": 2})])
        self.assertEqual([d.rule["type"] for d in
                          parse("At most 48 hours a week and 5 duties a week.", INST)],
                         ["hours_per_window", "max_working_days_per_window"])

    def test_a_limit_on_the_shift_and_a_limit_on_the_person_come_apart(self):
        found = parse("Every night shift needs at least 2 people on site, and no one "
                      "does more than 4 nights in the month.", INST)
        self.assertEqual([(d.rule["type"], d.rule["params"]) for d in found],
                         [("headcount_per_shift", {"shift": "N", "min": 2}),
                          ("max_night_shifts", {"max": 4})])

    def test_a_range_over_one_subject_stays_whole(self):
        self.assertEqual(read("Between 8 and 22 duties in the month."),
                         ("total_shifts_range", {"min": 8, "max": 22}))
        self.assertEqual(read("Give at most 4 nights and at least 1 night to everyone."),
                         ("shift_type_count_range", {"shift": "N", "min": 1, "max": 4}))

    def test_two_names_joined_by_and_stay_one_rule(self):
        draft = only("Staff 07 and Staff 09 are on leave on 20 September.")
        self.assertEqual(draft.rule["scope"], {"kind": "employees",
                                               "ids": ["E07", "E09"]})

    def test_splitting_is_reported_by_the_splitter_itself(self):
        self.assertEqual(len(split_compound("At most 6 days in a row and at most "
                                            "48 hours a week.")), 2)
        self.assertEqual(len(split_compound("Staff 07 and Staff 09 are on leave.")), 1)
        self.assertEqual(subject_of("at most 48 hours a week"), "hours")
        self.assertEqual(subject_of("be nice to each other"), "")


class TestWhatTheParserRefuses(unittest.TestCase):
    """A refusal the admin can act on beats a draft that quietly means something else."""

    def test_a_sentence_about_nothing_in_the_roster(self):
        self.assertIn("could not", refused("Coffee tastes better at 3am.").lower())

    def test_a_nearest_type_is_offered_when_the_words_are_close(self):
        draft = only("Please look after the weekend situation.")
        self.assertFalse(draft.ok)
        self.assertTrue(draft.suggestions, draft.problem)
        for name in draft.suggestions:
            self.assertIn(name, REGISTRY)

    def test_a_limit_with_no_number(self):
        draft = only("Nobody may work too many days in a row.")
        self.assertIn("could not tell", draft.problem)
        self.assertIn("max_consecutive_working_days", draft.suggestions)

    def test_a_date_outside_the_month_being_rostered(self):
        self.assertIn("outside", refused("Staff 07 is on leave on 5 December."))

    def test_a_person_who_is_not_on_the_staff_list(self):
        self.assertIn("staff 99", refused("Staff 99 is on leave on 20 September."))

    def test_a_group_that_is_not_a_role_or_a_contract(self):
        problem = refused("Staff on probation may not do nights.")
        self.assertIn("probation", problem)

    def test_a_shift_the_roster_does_not_have(self):
        problem = refused("Nobody may do the twilight shift twice in a row.")
        self.assertTrue(problem)

    def test_demand_per_role_is_out_of_reach_and_says_so(self):
        problem = refused("At least 2 DSG staff must be on every morning shift.")
        self.assertIn("role", problem.lower())


class TestTheOrderMatchersRun(unittest.TestCase):
    """Wordings that two families could both claim, and which one has to win."""

    def test_a_weekly_day_off_is_not_a_run_of_one_working_day(self):
        self.assertEqual(read("At least one day off every week."),
                         ("min_days_off_per_window", {"min": 1, "window": "calendar"}))

    def test_a_days_off_ceiling_is_refused_rather_than_flipped_quietly(self):
        problem = refused("At most 3 days off a week.")
        self.assertIn("working days", problem)
        self.assertEqual(read("Nobody may work more than 5 days a week."),
                         ("max_working_days_per_window",
                          {"max": 5, "window": "calendar"}))

    def test_a_working_day_floor_is_refused_with_what_to_say_instead(self):
        problem = refused("Staff must work at least 4 days a week.")
        self.assertIn("hours", problem)

    def test_a_named_day_is_a_day_rule_not_a_working_day_count(self):
        self.assertEqual(read("Staff 09 must not be rostered on 20 September.")[0],
                         "unavailable")

    def test_heads_at_night_is_not_a_nights_per_person_limit(self):
        self.assertEqual(read("At least 2 staff must be on the morning shift."),
                         ("headcount_per_shift", {"shift": "M", "min": 2}))
        self.assertEqual(read("Give everyone between 2 and 4 nights."),
                         ("shift_type_count_range", {"shift": "N", "min": 2, "max": 4}))

    def test_an_evening_shift_is_never_read_as_fairness(self):
        self.assertEqual(read("Staff 11 would rather avoid the evening shift."),
                         ("shift_preference", {"shift": "E", "direction": "avoid"}))

    def test_hours_in_a_day_is_never_read_as_a_count_of_days(self):
        problem = refused("Nobody may work more than 8 hours a day.")
        self.assertIn("shift", problem)
        self.assertEqual(read("Nobody may work more than 48 hours a week."),
                         ("hours_per_window", {"max_hours": 48}))


class TestWithNoRosterToCheckAgainst(unittest.TestCase):
    """Before the admin has entered staff and dates, the parser still has to be useful."""

    def test_a_rule_about_nobody_in_particular_still_reads(self):
        self.assertEqual(read("Nobody may work more than 6 days in a row.", None),
                         ("max_consecutive_working_days", {"max": 6}))

    def test_nothing_is_checked_and_the_draft_admits_it(self):
        draft = only("Nobody may work more than 6 days in a row.", None)
        self.assertTrue(any("nothing was checked" in note
                            for note in draft.assumptions), draft.assumptions)

    def test_a_named_person_cannot_be_resolved_yet(self):
        self.assertTrue(refused("Staff 07 is on leave from 15 to 19 September.", None))

    def test_a_bare_date_cannot_be_placed_without_a_month(self):
        self.assertTrue(refused("Nobody works on the 20th.", None))


class TestThePayloadTheServiceReturns(unittest.TestCase):
    """``parse_payload`` is what the API and the questionnaire actually consume."""

    def setUp(self):
        self.out = parse_payload(
            "Nobody may work more than 6 days in a row.\n"
            "Share night duty evenly.\n"
            "Coffee tastes better at 3am.\n", INST)

    def test_the_counts_add_up(self):
        counts = self.out["counts"]
        self.assertEqual(counts["statements"], 3)
        self.assertEqual(counts["drafted"], 2)
        self.assertEqual(counts["unparsed"], 1)
        self.assertEqual((counts["hard"], counts["soft"]), (1, 1))

    def test_the_drafts_keep_the_order_they_were_written_in(self):
        self.assertEqual([d["line"] for d in self.out["drafts"]], [1, 2, 3])

    def test_the_rule_list_holds_only_what_was_read(self):
        self.assertEqual([r["type"] for r in self.out["rules"]],
                         ["max_consecutive_working_days", "balance_workload"])

    def test_what_could_not_be_read_is_listed_on_its_own(self):
        self.assertEqual([d["line"] for d in self.out["unparsed"]], [3])
        self.assertTrue(self.out["unparsed"][0]["problem"])
        self.assertIsNone(self.out["unparsed"][0]["rule"])

    def test_every_draft_carries_the_words_it_came_from(self):
        for draft in self.out["drafts"]:
            self.assertTrue(draft["text"].strip())
            self.assertIn(draft["text"].split()[0].lower(),
                          "nobody share coffee".split())
            self.assertIn("assumptions", draft)
            self.assertIn("suggestions", draft)

    def test_the_whole_payload_survives_json(self):
        self.assertEqual(json.loads(json.dumps(self.out)), self.out)

    def test_a_confidence_is_reported_and_stays_honest(self):
        for draft in self.out["drafts"]:
            if draft["rule"]:
                self.assertGreaterEqual(draft["confidence"], 0.25)
                self.assertLessEqual(draft["confidence"], 0.98)

    def test_no_instance_is_reported_in_the_payload(self):
        without = parse_payload("Nobody may work more than 6 days in a row.", None)
        self.assertFalse(without["counts"]["checked_against_instance"])
        with_inst = parse_payload("Nobody may work more than 6 days in a row.", INST)
        self.assertTrue(with_inst["counts"]["checked_against_instance"])


class TestAStatementThatReadsMoreThanOneWay(unittest.TestCase):
    """Where the words are open, every reading is offered and none is chosen."""

    def test_a_ceiling_on_a_named_shift_with_no_stretch_reads_two_ways(self):
        draft = only("No more than 4 nights.")
        self.assertTrue(draft.ok)
        self.assertEqual([one["rule"]["type"] for one in draft.readings],
                         ["max_night_shifts", "max_consecutive_same_shift"])
        self.assertEqual([one["rule"]["params"] for one in draft.readings],
                         [{"max": 4}, {"max": 4, "shift": "N"}])

    def test_the_reading_the_draft_carries_is_the_first_one_offered(self):
        draft = only("No more than 4 nights.")
        self.assertEqual(draft.readings[0]["rule"], draft.rule)

    def test_every_reading_says_in_words_what_it_would_mean(self):
        for text in ("No more than 4 nights.", "Max 48 hours.",
                     "Everyone must work more than 12 duties."):
            for one in only(text).readings:
                self.assertTrue(one["means"].strip(), text)
                self.assertIn(one["rule"]["type"], REGISTRY, text)

    def test_a_stretch_in_the_words_leaves_one_reading_only(self):
        for text in ("No more than 3 nights in a row.",
                     "Nobody does more than 4 nights in the month.",
                     "No one works more than 48 hours a week.",
                     "Nobody may work more than 8 hours a day.",
                     "At least 11 hours off between two shifts."):
            self.assertEqual(only(text).readings, [], text)

    def test_more_than_with_nothing_forbidden_offers_the_floor_and_the_ceiling(self):
        draft = only("Everyone must work more than 12 duties.")
        self.assertEqual([one["rule"]["params"] for one in draft.readings][:2],
                         [{"min": 13}, {"max": 12}])
        self.assertEqual([one["rule"]["type"] for one in draft.readings],
                         ["total_shifts_range", "total_shifts_range",
                          "max_working_days_per_window"])

    def test_hours_with_no_stretch_offer_the_week_before_the_whole_period(self):
        draft = only("Max 48 hours.")
        self.assertEqual([one["rule"]["type"] for one in draft.readings],
                         ["hours_per_window", "total_hours_range"])

    def test_one_reading_is_no_choice_at_all_and_is_taken_as_the_draft(self):
        draft = only("Minimum 12 duties.")
        self.assertEqual((draft.rule["type"], draft.rule["params"]),
                         ("total_shifts_range", {"min": 12}))
        self.assertEqual(draft.readings, [])
        self.assertTrue(any("did not say over what stretch" in note
                            for note in draft.assumptions), draft.assumptions)

    def test_readings_are_never_the_same_rule_twice_and_never_crowd_the_page(self):
        for text in ("No more than 4 nights.", "Max 48 hours.", "Minimum 12 duties.",
                     "Everyone must work more than 12 duties.",
                     "Cap the evening shift at 5."):
            shapes = [(one["rule"]["type"], sorted(one["rule"]["params"].items()))
                      for one in only(text).readings]
            self.assertEqual(len(shapes), len(set(map(str, shapes))), text)
            self.assertLessEqual(len(shapes), Parser.MOST_READINGS, text)

    def test_a_shared_reading_is_never_reported_as_near_certain(self):
        for text in ("No more than 4 nights.", "Max 48 hours."):
            draft = only(text)
            self.assertLessEqual(draft.confidence, Parser.SHARED, text)
            for one in draft.readings:
                self.assertLessEqual(one["confidence"], Parser.SHARED, text)
                self.assertGreaterEqual(one["confidence"], 0.25, text)

    def test_the_choice_is_said_out_loud_in_the_assumptions(self):
        draft = only("No more than 4 nights.")
        self.assertTrue(any("reads more than one way" in note
                            for note in draft.assumptions), draft.assumptions)

    def test_the_readings_reach_the_payload_and_survive_json(self):
        out = parse_payload("No more than 4 nights.", INST)
        again = json.loads(json.dumps(out))
        self.assertEqual(len(again["drafts"][0]["readings"]), 2)
        self.assertEqual(again["drafts"][0]["readings"][0]["rule"],
                         again["drafts"][0]["rule"])

    def test_only_the_reading_the_draft_carries_is_offered_as_a_rule(self):
        out = parse_payload("No more than 4 nights.", INST)
        self.assertEqual(len(out["rules"]), 1)
        self.assertEqual(out["rules"][0]["type"], "max_night_shifts")

    def test_every_reading_builds_under_a_fresh_ruleset(self):
        for text in ("No more than 4 nights.", "Max 48 hours.",
                     "Everyone must work more than 12 duties."):
            for one in only(text).readings:
                rules = [Rule.from_dict(one["rule"])]
                RuleSet(replace(INST, rules=rules))


class TestEveryDraftIsARuleTheEngineAccepts(unittest.TestCase):
    """The promise of the parser: a draft the admin confirms cannot fail to build."""

    def test_the_reference_rules_all_come_back_from_their_own_labels(self):
        same = []
        for rule in INST.rules:
            drafts = parse(rule.label, INST)
            self.assertTrue(drafts, rule.label)
            for draft in drafts:
                self.assertTrue(draft.ok, f"{rule.label}: {draft.problem}")
            same.append(all(d.rule["type"] == rule.type for d in drafts))
        self.assertTrue(all(same),
                        [r.label for r, ok in zip(INST.rules, same) if not ok])

    def test_every_drafted_rule_builds_under_a_fresh_ruleset(self):
        text = "\n".join(rule.label for rule in INST.rules)
        out = parse_payload(text, INST)
        rules = [Rule.from_dict(data) for data in out["rules"]]
        RuleSet(replace(INST, rules=rules))

    def test_a_policy_written_as_prose_drafts_and_solves(self):
        text = ("Every duty must be staffed.\n"
                "Nobody may work more than 6 days in a row.\n"
                "At least one day off every week.\n"
                "A night shift must not be followed by a morning shift.\n"
                "Share night duty evenly.\n")
        out = parse_payload(text, INST)
        self.assertEqual(out["counts"]["unparsed"], 0)
        rules = [Rule.from_dict(data) for data in out["rules"]]
        built = RuleSet(replace(INST, rules=rules))
        self.assertEqual(len(built.evaluators), 5)

    def test_the_parser_only_ever_names_registered_rule_types(self):
        for rule in INST.rules:
            for draft in parse(rule.label, INST):
                self.assertIn(draft.rule["type"], REGISTRY)

    def test_a_parser_can_be_reused_and_never_repeats_a_rule_id(self):
        parser = Parser(INST)
        first = parser.parse("Nobody may work more than 6 days in a row.")[0].rule
        second = parser.parse("Nobody may work more than 6 days in a row.")[0].rule
        self.assertNotEqual(first["id"], second["id"])
        for key in ("type", "params", "scope", "severity"):
            self.assertEqual(first[key], second[key])


if __name__ == "__main__":
    unittest.main()
