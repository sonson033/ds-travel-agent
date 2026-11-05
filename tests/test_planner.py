import pytest

from travel_agent import config
from travel_agent.checker import PlanChecker
from travel_agent.data import load_json
from travel_agent.planner import Planner
from travel_agent.tools import TravelTools

PERSONAS = load_json(config.PERSONAS_FILE)
CASES = {c["request_id"]: c for c in load_json(config.EVAL_CASES_FILE)["requests"]}


def planner(fault_rates=None):
    return Planner(TravelTools(fault_rates={} if fault_rates is None else fault_rates), PERSONAS)


def constraints(request_id, **changes):
    return {**CASES[request_id]["constraints"], **changes}


def test_r01_cheapest_plan_after_workshop():
    result = planner().plan("T1", constraints("R01"))
    assert result["status"] == "PLAN"
    assert result["plan"]["flights"] == {"outbound": "FL-0003", "return": "FL-0004"}
    assert result["plan"]["hotel"] == {"hotel_id": "HT-081", "nights": 3}
    assert result["total_price"] == 351


def test_r03_avoids_ht086_and_warns_about_short_gap():
    result = planner().plan("T3", constraints("R03"))
    assert result["status"] == "PLAN"
    assert result["plan"]["flights"]["outbound"] == "FL-0012"
    assert result["plan"]["hotel"]["hotel_id"] == "HT-052"
    assert len(result["warnings"]) == 1 and "School" in result["warnings"][0]


def test_r08_declines_because_of_birthday():
    result = planner().plan("T2", constraints("R08"))
    assert result["status"] == "DECLINE"
    assert "birthday" in result["reasons"][0]


def test_r10_declines_over_budget_with_cheapest_price():
    result = planner().plan("T1", constraints("R10"))
    assert result["status"] == "DECLINE"
    assert result["total_price"] == 289
    assert "289" in result["reasons"][0]


def test_d5_friend_joins_r01_is_over_budget():
    result = planner().plan("T1", constraints("R01", party=2))
    assert result["status"] == "DECLINE"
    assert result["total_price"] == 498


def test_flexible_destination_picks_cheapest_city():
    # R04 after asking for the dates: warm city, 13-16 Nov, under 800
    result = planner().plan("T1", {"destination": None, "party": 1, "start_date": "2026-11-13",
                                   "end_date": "2026-11-16", "budget_total": 800})
    assert result["status"] == "PLAN"
    assert result["plan"]["destination"] == "LIS"


@pytest.mark.parametrize("request_id,persona_id", [("R01", "T1"), ("R03", "T3"), ("R09", "T2")])
def test_planned_trips_pass_the_checker(request_id, persona_id):
    result = planner().plan(persona_id, constraints(request_id))
    check = PlanChecker().check(result["plan"], constraints(request_id))
    assert check["valid"], check["violations"]
    assert check["total_price"] == result["total_price"]


def test_hotel_details_always_down_means_no_blind_hotel():
    result = planner({"hotel_details": {"timeout_rate": 1.0}}).plan("T3", constraints("R03"))
    assert result["status"] == "DECLINE"
    assert result["plan"] is None
    assert any("no details" in f for f in result["failures"])


def test_flight_search_always_down_is_reported_as_failure_not_as_no_flights():
    result = planner({"flight_search": {"timeout_rate": 1.0}}).plan("T1", constraints("R01"))
    assert result["status"] == "DECLINE"
    assert "tool failures" in result["reasons"][0]


def test_r02_gets_one_activity_per_full_day_and_passes_checker():
    result = planner().plan("T2", constraints("R02"))
    assert result["status"] == "PLAN"
    assert [a["date"] for a in result["plan"]["activities"]] == ["2026-11-21", "2026-11-22"]
    check = PlanChecker().check(result["plan"], constraints("R02"))
    assert check["valid"], check["violations"]
    assert check["total_price"] == result["total_price"]


def test_d3_storm_saturday_gets_indoor_activity():
    cons = constraints("R02", no_outdoor_dates=["2026-11-21"])
    result = planner().plan("T2", cons)
    check = PlanChecker().check(result["plan"], cons)
    assert check["valid"], check["violations"]


def test_d2_budget_cut_still_fits():
    result = planner().plan("T2", constraints("R02", budget_total=770))
    assert result["status"] == "PLAN"
    assert result["total_price"] <= 770


def test_activity_search_always_empty_is_a_tool_failure():
    result = planner({"activity_search": {"empty_result_rate": 1.0}}).plan("T2", constraints("R02"))
    assert result["status"] == "DECLINE"
    assert "tool failures" in result["reasons"][0]


def test_weather_always_down_plans_indoor_and_reports_it():
    result = planner({"weather": {"timeout_rate": 1.0}}).plan("T2", constraints("R02"))
    assert result["status"] == "PLAN"
    activities = {a["activity_id"]: a for a in load_json(config.ACTIVITIES_FILE)}
    assert not any(activities[a["activity_id"]]["outdoor"] for a in result["plan"]["activities"])
    assert any("no weather" in f for f in result["failures"])


def test_default_fault_rates_are_recovered_by_retries():
    tools = TravelTools()  # seed 1234 and rates from fault_config.json
    result = Planner(tools, PERSONAS).plan("T1", constraints("R01"))
    assert result["status"] == "PLAN"
    assert result["total_price"] == 351
    assert any(c["outcome"] != "ok" for c in tools.call_log)  # failures happened and were handled
