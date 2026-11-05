"""Sanity checks for eval/cases.json: complete, and the reference plans really are valid."""

import pytest

from travel_agent import config
from travel_agent.checker import PlanChecker
from travel_agent.data import load_json, load_jsonl

CASES = load_json(config.EVAL_CASES_FILE)
PERSONA_OF = {r["request_id"]: r["persona_id"] for r in load_jsonl(config.TRIP_REQUESTS_FILE)}


def test_every_request_and_disruption_has_a_case():
    assert sorted(c["request_id"] for c in CASES["requests"]) == sorted(PERSONA_OF)
    disruption_ids = [d["event_id"] for d in load_jsonl(config.DISRUPTIONS_FILE)]
    assert sorted(c["event_id"] for c in CASES["disruptions"]) == sorted(disruption_ids)


def test_expected_values_are_known():
    for case in CASES["requests"] + CASES["disruptions"]:
        assert case["expected"] in {"PLAN", "ASK", "DECLINE"}


@pytest.mark.parametrize("case", [c for c in CASES["requests"] if "reference_plan" in c], ids=lambda c: c["request_id"])
def test_reference_plans_are_valid(case):
    cons = case["constraints"]
    plan = {"persona_id": PERSONA_OF[case["request_id"]], "party": cons["party"], "destination": cons["destination"],
            "start_date": cons["start_date"], "end_date": cons["end_date"], **case["reference_plan"]}
    result = PlanChecker().check(plan, cons)
    assert result["valid"], result["violations"]
