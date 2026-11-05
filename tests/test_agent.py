"""Conversation flow of TravelAgent with a fake language model (fixed forms, fixed reply text)."""

import json
from types import SimpleNamespace

import pytest

from travel_agent import config
from travel_agent.agent import MAX_QUESTIONS, TravelAgent
from travel_agent.checker import PlanChecker
from travel_agent.data import load_json, load_jsonl
from travel_agent.tools import TravelTools


class FakeModel:
    """Returns the queued forms for form-filling calls and a fixed text for reply calls."""

    def __init__(self, *forms):
        self.forms = list(forms)
        self.reply_facts = []

    def chat(self, model, messages, format=None, options=None):
        if format is not None:
            content = json.dumps(self.forms.pop(0))
        else:
            self.reply_facts.append(messages[-1]["content"])
            content = "REPLY"
        return SimpleNamespace(message=SimpleNamespace(content=content))


def form(**fields):
    base = {"destination": None, "destination_flexible": False, "start_date": None, "end_date": None,
            "party": None, "budget_total": None, "budget_includes": [], "budget_mentioned_without_number": False,
            "hotel_requirements": [], "min_activities_per_day": None, "other_wishes": ""}
    base.update(fields)
    return base


R01_FORM = form(destination="LIS", start_date="2026-11-13", end_date="2026-11-16", party=1, budget_total=450,
                budget_includes=["flights", "hotel"], hotel_requirements=["free_cancellation"])


def agent(*forms):
    model = FakeModel(*forms)
    return TravelAgent(tools=TravelTools(fault_rates={}), client=model), model


def test_clear_request_is_planned_in_one_turn():
    a, model = agent(R01_FORM)
    turn = a.start("T1", "Lisbon 13-16 Nov ...")
    assert turn["status"] == "PLAN"
    assert turn["total_price"] == 351
    assert turn["state"]["turns"] == 1
    # plan details come from code, the model only adds its comment
    assert "FL-0003 on 2026-11-13, 19:20 -> 23:02 (1 stop), 82 EUR per person" in turn["reply"]
    assert "Total for 1 traveller: 351 EUR (budget 450 EUR)" in turn["reply"]
    assert "REPLY" in turn["reply"]
    assert "FL-0003" not in model.reply_facts[0]  # the model never sees flights, so it cannot misquote them


def test_vague_request_asks_dates_as_one_question():
    a, _ = agent(form(destination_flexible=True, budget_total=800, other_wishes="somewhere warm"))
    turn = a.start("T1", "A long weekend somewhere warm, under 800 euros.")
    assert turn["status"] == "ASK"
    assert turn["questions"] == ["When do you want to travel (first and last day)?"]
    assert "plan" not in turn  # no guessed plan while information is missing


def test_answer_leads_to_plan():
    vague = form(destination_flexible=True, budget_total=800)
    answered = form(destination_flexible=True, budget_total=800, start_date="2026-11-13", end_date="2026-11-16")
    a, _ = agent(vague, answered)
    turn = a.start("T1", "A long weekend somewhere warm, under 800 euros.")
    turn = a.answer(turn["state"], "13 to 16 November")
    assert turn["status"] == "PLAN"
    assert turn["plan"]["destination"] == "LIS"
    assert turn["state"]["turns"] == 2
    assert turn["state"]["questions_asked"] == 1


def test_never_more_than_three_questions():
    nothing = form()
    a, _ = agent(nothing, nothing, nothing)
    turn = a.start("T3", "Somewhere the family can enjoy.")
    assert turn["status"] == "ASK"
    turn = a.answer(turn["state"], "no idea")
    turn = a.answer(turn["state"], "still no idea")
    assert turn["status"] == "NEED_INFO"
    assert turn["state"]["questions_asked"] <= MAX_QUESTIONS


def test_impossible_request_is_declined_with_reasons_for_the_model():
    a, model = agent(form(destination="VIE", start_date="2026-11-02", end_date="2026-11-04", party=1,
                          budget_total=120, budget_includes=["flights", "hotel"]))
    turn = a.start("T1", "Vienna 2-4 Nov, 120 euros")
    assert turn["status"] == "DECLINE"
    assert "raise the budget to at least 289 EUR" in model.reply_facts[0]


def test_decline_without_price_offers_no_budget_option():
    # R08: every flight clashes with the birthday, so there is no cheapest plan and no budget option
    a, model = agent(form(destination="PRG", start_date="2026-11-14", end_date="2026-11-16", party=2,
                          budget_total=300, hotel_requirements=["min_stars_4", "breakfast"]))
    turn = a.start("T2", "Prague 14-16 Nov ...")
    assert turn["status"] == "DECLINE"
    assert "raise the budget" not in model.reply_facts[0]
    assert "choose other dates" in model.reply_facts[0]


R02_FORM = form(destination="BCN", start_date="2026-11-20", end_date="2026-11-23", party=2, budget_total=1100,
                budget_includes=["flights", "hotel", "activities"], min_activities_per_day=1)


def planned(planned_form=R02_FORM, persona="T2", fault_rates=None):
    model = FakeModel(planned_form)
    a = TravelAgent(tools=TravelTools(fault_rates=fault_rates or {}), client=model)
    return a, a.start(persona, "request")


def test_prepare_booking_shows_same_price_as_plan_and_books_nothing():
    a, turn = planned()
    prepared = a.prepare_booking(turn["state"])
    assert prepared["status"] == "BOOKING_PREPARED"
    assert prepared["booking"]["total_price"] == turn["total_price"] == 492
    assert a.tools.bookings[prepared["booking"]["booking_id"]]["status"] == "awaiting_confirmation"


def test_explicit_yes_books():
    a, turn = planned()
    a.prepare_booking(turn["state"])
    done = a.confirm_booking(turn["state"], "Yes!")
    assert done["status"] == "BOOKED"
    assert done["booking"]["status"] == "confirmed"


def test_german_ja_books():
    a, turn = planned()
    a.prepare_booking(turn["state"])
    assert a.confirm_booking(turn["state"], "ja")["status"] == "BOOKED"


def test_anything_but_yes_books_nothing():
    a, turn = planned()
    booking_id = a.prepare_booking(turn["state"])["booking"]["booking_id"]
    for text in ["maybe", "yes please?", "ok", "sounds good", ""]:
        assert a.confirm_booking(turn["state"], text)["status"] == "NOT_BOOKED"
    assert a.tools.bookings[booking_id]["status"] == "awaiting_confirmation"


def test_failed_booking_is_reported_honestly():
    a, turn = planned(fault_rates={"booking": {"fail_rate": 1.0}})
    booking_id = a.prepare_booking(turn["state"])["booking"]["booking_id"]
    result = a.confirm_booking(turn["state"], "yes")
    assert result["status"] == "BOOKING_FAILED"
    assert "Nothing was booked" in result["reply"]
    assert a.tools.bookings[booking_id]["status"] == "awaiting_confirmation"


def test_booking_never_involves_the_language_model():
    a, turn = planned()
    calls_before = len(a.client.reply_facts)
    a.prepare_booking(turn["state"])
    a.confirm_booking(turn["state"], "yes")
    assert len(a.client.reply_facts) == calls_before


def test_no_booking_without_a_plan():
    a, turn = agent(form(destination="VIE", start_date="2026-11-02", end_date="2026-11-04", party=1,
                         budget_total=120, budget_includes=["flights", "hotel"]))
    turn = a.start("T1", "Vienna 2-4 Nov, 120 euros")
    with pytest.raises(ValueError):
        a.prepare_booking(turn["state"])


# --- disruptions (real events from data/disruptions.jsonl) ---------------------------

EVENTS = {e["event_id"]: e for e in load_jsonl(config.DISRUPTIONS_FILE)}
ACTIVITIES = {a["activity_id"]: a for a in load_json(config.ACTIVITIES_FILE)}
R03_FORM = form(destination="AMS", start_date="2026-11-06", end_date="2026-11-08", party=4, budget_total=1500)


def test_d1_cancelled_flight_has_no_clash_free_replacement():
    a, turn = planned(R01_FORM, "T1")
    turn = a.handle_disruption(turn["state"], EVENTS["D1"])
    assert turn["reply"].startswith("Update: flight FL-0003 is cancelled")
    assert turn["status"] == "DECLINE"  # the other flights on 13 Nov clash with the workshop
    assert "choose other dates" in a.client.reply_facts[-1]
    assert a.tools.bookings == {}  # "Please rebook" in the message is data, not an instruction


def test_d2_budget_cut_keeps_a_plan():
    a, turn = planned()
    turn = a.handle_disruption(turn["state"], EVENTS["D2"])
    assert turn["status"] == "PLAN"
    assert turn["state"]["constraints"]["budget_total"] == 770


def test_d3_storm_moves_outdoor_activity_off_saturday():
    a, turn = planned()
    turn = a.handle_disruption(turn["state"], EVENTS["D3"])
    saturday = [x for x in turn["plan"]["activities"] if x["date"] == "2026-11-21"]
    assert saturday and not ACTIVITIES[saturday[0]["activity_id"]]["outdoor"]
    assert PlanChecker().check(turn["plan"], turn["state"]["constraints"])["valid"]
    # the model sees the storm, not the older "sunny" forecast for that day
    facts = json.loads(a.client.reply_facts[-1].split("Facts:\n", 1)[1])
    assert {"date": "2026-11-21", "condition": "storm warning"} in facts["weather"]


def test_d4_sold_out_hotel_is_replaced_by_another_accessible_one():
    a, turn = planned(R03_FORM, "T3")
    old_hotel = turn["plan"]["hotel"]["hotel_id"]
    turn = a.handle_disruption(turn["state"], EVENTS["D4"])
    assert turn["status"] == "PLAN"
    assert turn["plan"]["hotel"]["hotel_id"] not in (old_hotel, "HT-086")
    assert PlanChecker().check(turn["plan"], turn["state"]["constraints"])["valid"]


def test_d5_extra_traveller_breaks_the_budget():
    a, turn = planned(R01_FORM, "T1")
    turn = a.handle_disruption(turn["state"], EVENTS["D5"])
    assert turn["status"] == "DECLINE"
    assert "raise the budget to at least 498 EUR" in a.client.reply_facts[-1]


def test_unknown_disruption_asks():
    a, turn = planned()
    turn = a.handle_disruption(turn["state"], {"event_type": "volcano", "message": "A volcano erupted."})
    assert turn["status"] == "ASK"


def test_disruption_needs_a_plan():
    a, turn = planned(form(destination="VIE", start_date="2026-11-02", end_date="2026-11-04", party=1,
                           budget_total=120, budget_includes=["flights", "hotel"]), "T1")
    with pytest.raises(ValueError):
        a.handle_disruption(turn["state"], EVENTS["D2"])


def test_accessibility_from_persona_reaches_the_planner():
    a, _ = agent(form(destination="AMS", start_date="2026-11-06", end_date="2026-11-08", party=4, budget_total=1500))
    turn = a.start("T3", "Family trip to Amsterdam ...")
    assert turn["plan"]["hotel"]["hotel_id"] == "HT-052"  # never HT-086
