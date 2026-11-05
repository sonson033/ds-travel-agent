import pytest

from travel_agent.checker import PlanChecker


@pytest.fixture(scope="module")
def checker():
    return PlanChecker()


def r01_plan(**changes):
    plan = {
        "request_id": "R01", "persona_id": "T1", "party": 1, "destination": "LIS",
        "start_date": "2026-11-13", "end_date": "2026-11-16",
        "flights": {"outbound": "FL-0003", "return": "FL-0004"},
        "hotel": {"hotel_id": "HT-081", "nights": 3},
    }
    plan.update(changes)
    return plan


R01_CONSTRAINTS = {
    "destination": "LIS", "party": 1, "start_date": "2026-11-13", "end_date": "2026-11-16",
    "budget_total": 450, "budget_includes": ["flights", "hotel"], "hotel_requirements": ["free_cancellation"],
}


def rules(result):
    return [v["rule"] for v in result["violations"]]


# --- flights, request match, calendar ------------------------------------

def test_valid_r01_plan(checker):
    result = checker.check(r01_plan(), R01_CONSTRAINTS)
    assert result == {"valid": True, "violations": [], "warnings": [], "total_price": 351.0}


def test_flight_during_workshop_is_calendar_conflict(checker):
    result = checker.check(r01_plan(flights={"outbound": "FL-0001", "return": "FL-0004"}), R01_CONSTRAINTS)
    assert not result["valid"]
    assert rules(result) == ["calendar_conflict"]
    assert "Team workshop" in result["violations"][0]["message"]


def test_missing_field(checker):
    plan = r01_plan()
    del plan["flights"]
    assert rules(checker.check(plan, R01_CONSTRAINTS)) == ["missing_field"]


def test_unknown_flight(checker):
    result = checker.check(r01_plan(flights={"outbound": "FL-9999", "return": "FL-0004"}), R01_CONSTRAINTS)
    assert rules(result) == ["unknown_flight"]


def test_wrong_route(checker):
    # FL-0006 flies MUC -> BCN on 20 Nov
    result = checker.check(r01_plan(flights={"outbound": "FL-0006", "return": "FL-0004"}), R01_CONSTRAINTS)
    assert "wrong_route" in rules(result)


def test_wrong_date(checker):
    # FL-0028 flies BER -> LIS on 10 Nov
    result = checker.check(r01_plan(flights={"outbound": "FL-0028", "return": "FL-0004"}), R01_CONSTRAINTS)
    assert "wrong_date" in rules(result)


def test_plan_must_match_request(checker):
    result = checker.check(r01_plan(party=2), R01_CONSTRAINTS)
    assert "party_mismatch" in rules(result)


def r03_plan(outbound, hotel_id="HT-052"):
    return {
        "request_id": "R03", "persona_id": "T3", "party": 4, "destination": "AMS",
        "start_date": "2026-11-06", "end_date": "2026-11-08",
        "flights": {"outbound": outbound, "return": "FL-0015"},
        "hotel": {"hotel_id": hotel_id, "nights": 2},
    }


R03_CONSTRAINTS = {
    "destination": "AMS", "party": 4, "start_date": "2026-11-06", "end_date": "2026-11-08",
    "budget_total": 1500, "hotel_requirements": ["step_free_with_elevator"],
}


def test_not_enough_seats_for_family(checker):
    # FL-0013 has 2 seats left
    assert rules(checker.check(r03_plan("FL-0013"), R03_CONSTRAINTS)) == ["not_enough_seats"]


def test_flight_70_minutes_after_school_is_valid_with_warning(checker):
    result = checker.check(r03_plan("FL-0012"), R03_CONSTRAINTS)
    assert result["valid"]
    assert [w["rule"] for w in result["warnings"]] == ["tight_schedule"]
    assert "70 min" in result["warnings"][0]["message"]


def test_flight_during_school_is_calendar_conflict(checker):
    assert rules(checker.check(r03_plan("FL-0011"), R03_CONSTRAINTS)) == ["calendar_conflict"]


def r08_plan(outbound, hotel_id="HT-087"):
    return {"persona_id": "T2", "party": 2, "destination": "PRG", "start_date": "2026-11-14",
            "end_date": "2026-11-16", "flights": {"outbound": outbound, "return": "FL-0023"},
            "hotel": {"hotel_id": hotel_id, "nights": 2}}


R08_CONSTRAINTS = {"destination": "PRG", "party": 2, "start_date": "2026-11-14", "end_date": "2026-11-16",
                   "budget_total": 300, "hotel_requirements": ["min_stars_4", "breakfast"]}


def test_r08_every_outbound_flight_clashes_with_birthday(checker):
    for outbound in ["FL-0020", "FL-0021"]:
        assert "calendar_conflict" in rules(checker.check(r08_plan(outbound), R08_CONSTRAINTS))


# --- budget ------------------------------------------------------------------

def test_r01_with_friend_is_over_budget(checker):
    # D5: a second traveller, everything else the same
    constraints = {**R01_CONSTRAINTS, "party": 2}
    result = checker.check(r01_plan(party=2), constraints)
    assert result["total_price"] == 2 * (82 + 65) + 3 * 68  # 498
    assert rules(result) == ["over_budget"]


def test_r08_is_over_budget_even_with_cheapest_flights(checker):
    result = checker.check(r08_plan("FL-0021"), R08_CONSTRAINTS)
    assert result["total_price"] == 2 * (79 + 81) + 2 * 105  # 530
    assert "over_budget" in rules(result)


def test_budget_uses_higher_hotel_price(checker):
    # HT-005: listing 117, details 134 per night
    result = checker.check(r01_plan(hotel={"hotel_id": "HT-005", "nights": 3}), {})
    assert result["total_price"] == 82 + 65 + 3 * 134


# --- hotel ---------------------------------------------------------------------

def test_missing_hotel(checker):
    plan = r01_plan()
    del plan["hotel"]
    assert rules(checker.check(plan, R01_CONSTRAINTS)) == ["missing_hotel"]


def test_unknown_hotel(checker):
    assert rules(checker.check(r01_plan(hotel={"hotel_id": "HT-999", "nights": 3}), R01_CONSTRAINTS)) == ["unknown_hotel"]


def test_hotel_in_wrong_city(checker):
    result = checker.check(r01_plan(hotel={"hotel_id": "HT-049", "nights": 3}), {})
    assert rules(result) == ["hotel_wrong_city"]


def test_wrong_number_of_nights(checker):
    result = checker.check(r01_plan(hotel={"hotel_id": "HT-081", "nights": 2}), R01_CONSTRAINTS)
    assert rules(result) == ["wrong_nights"]


def test_ht086_accessibility_is_unconfirmed(checker):
    # listing: step-free, details: not step-free
    result = checker.check(r03_plan("FL-0012", hotel_id="HT-086"), R03_CONSTRAINTS)
    assert rules(result) == ["hotel_requirement_unconfirmed"]
    assert "listing says True, details say False" in result["violations"][0]["message"]


def test_hotel_without_accessibility(checker):
    # HT-051: neither source says step-free
    assert rules(checker.check(r03_plan("FL-0012", hotel_id="HT-051"), R03_CONSTRAINTS)) == ["hotel_requirement_not_met"]


def test_non_free_cancellation_hotel(checker):
    # HT-003: listing non_refundable, details free_until_48h -> neither is free cancellation
    result = checker.check(r01_plan(hotel={"hotel_id": "HT-003", "nights": 3}), R01_CONSTRAINTS)
    assert rules(result) == ["hotel_requirement_not_met", "over_budget"]  # 82 + 65 + 3 * 119 = 504


def test_four_star_hotel_without_breakfast(checker):
    # HT-027: 4 stars, no breakfast
    result = checker.check(r08_plan("FL-0021", hotel_id="HT-027"), {**R08_CONSTRAINTS, "budget_total": None})
    assert "hotel_requirement_not_met" in rules(result)
    assert "breakfast" in result["violations"][-1]["message"]


def test_cancelled_flight_and_sold_out_hotel_are_violations(checker):
    constraints = {**R01_CONSTRAINTS, "excluded_flights": ["FL-0003"], "excluded_hotels": ["HT-081"]}
    assert rules(checker.check(r01_plan(), constraints)) == ["excluded_item_used", "excluded_item_used"]


def test_unknown_hotel_requirement_raises(checker):
    with pytest.raises(ValueError):
        checker.check(r01_plan(), {"hotel_requirements": ["sea_view"]})


# --- activities ------------------------------------------------------------------

def r02_plan(activities=None):
    if activities is None:
        activities = [
            {"activity_id": "AC-016", "date": "2026-11-21"},  # boat trip, outdoor, 8 EUR (Sat)
            {"activity_id": "AC-013", "date": "2026-11-22"},  # museum, indoor, 35 EUR (Sun)
        ]
    return {
        "request_id": "R02", "persona_id": "T2", "party": 2, "destination": "BCN",
        "start_date": "2026-11-20", "end_date": "2026-11-23",
        "flights": {"outbound": "FL-0008", "return": "FL-0010"},
        "hotel": {"hotel_id": "HT-083", "nights": 3},
        "activities": activities,
    }


R02_CONSTRAINTS = {
    "destination": "BCN", "party": 2, "start_date": "2026-11-20", "end_date": "2026-11-23",
    "budget_total": 1100, "budget_includes": ["flights", "hotel", "activities"], "min_activities_per_day": 1,
}


def test_valid_r02_plan_includes_activities_in_budget(checker):
    result = checker.check(r02_plan(), R02_CONSTRAINTS)
    assert result["valid"], result["violations"]
    assert result["total_price"] == 2 * (69 + 74) + 3 * 58 + 2 * (8 + 35)  # 546


def test_activities_not_in_budget_unless_included(checker):
    constraints = {**R02_CONSTRAINTS, "budget_includes": ["flights", "hotel"]}
    assert checker.check(r02_plan(), constraints)["total_price"] == 2 * (69 + 74) + 3 * 58


def test_full_day_without_activity(checker):
    result = checker.check(r02_plan([{"activity_id": "AC-016", "date": "2026-11-21"}]), R02_CONSTRAINTS)
    assert rules(result) == ["too_few_activities"]
    assert "2026-11-22" in result["violations"][0]["message"]


def test_arrival_and_departure_day_need_no_activity(checker):
    # option B: only Sat 21 and Sun 22 are full days
    assert checker.check(r02_plan(), R02_CONSTRAINTS)["valid"]


def test_activity_closed_on_monday(checker):
    # AC-011 Barcelona food tour is closed on Mondays; 23 Nov is a Monday
    activities = r02_plan()["activities"] + [{"activity_id": "AC-011", "date": "2026-11-23"}]
    assert rules(checker.check(r02_plan(activities), R02_CONSTRAINTS)) == ["activity_closed"]


def test_activity_outside_trip(checker):
    activities = r02_plan()["activities"] + [{"activity_id": "AC-013", "date": "2026-11-25"}]
    assert rules(checker.check(r02_plan(activities), R02_CONSTRAINTS)) == ["activity_outside_trip"]


def test_activity_in_wrong_city(checker):
    activities = r02_plan()["activities"] + [{"activity_id": "AC-001", "date": "2026-11-21"}]  # Lisbon
    assert rules(checker.check(r02_plan(activities), R02_CONSTRAINTS)) == ["activity_wrong_city"]


def test_unknown_activity_and_missing_date(checker):
    activities = r02_plan()["activities"] + [{"activity_id": "AC-999", "date": "2026-11-21"},
                                             {"activity_id": "AC-013"}]
    assert rules(checker.check(r02_plan(activities), R02_CONSTRAINTS)) == ["unknown_activity", "activity_without_date"]


def test_d3_storm_blocks_outdoor_activity_on_saturday(checker):
    constraints = {**R02_CONSTRAINTS, "no_outdoor_dates": ["2026-11-21"]}
    result = checker.check(r02_plan(), constraints)
    # the boat trip violates the storm day and no longer counts for Saturday
    assert rules(result) == ["outdoor_on_blocked_day", "too_few_activities"]


def test_d3_replanned_with_indoor_activity_is_valid(checker):
    constraints = {**R02_CONSTRAINTS, "no_outdoor_dates": ["2026-11-21"]}
    activities = [{"activity_id": "AC-018", "date": "2026-11-21"},  # cooking workshop, indoor
                  {"activity_id": "AC-013", "date": "2026-11-22"}]
    assert checker.check(r02_plan(activities), constraints)["valid"]


def test_r09_outdoor_hike_in_rain_gives_warnings(checker):
    plan = {"persona_id": "T2", "party": 2, "destination": "AMS", "start_date": "2026-11-27",
            "end_date": "2026-11-29", "flights": {"outbound": "FL-0017", "return": "FL-0019"},
            "hotel": {"hotel_id": "HT-055", "nights": 2},
            "activities": [{"activity_id": "AC-068", "date": "2026-11-28"}]}  # outdoor hike, 0 EUR
    result = checker.check(plan, {"destination": "AMS", "party": 2})
    assert result["valid"]
    assert [w["rule"] for w in result["warnings"]] == ["outdoor_in_rain", "unverified_price"]
