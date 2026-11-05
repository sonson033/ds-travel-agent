"""Tests for the fixed rules in complete_form (no language model needed)."""

from travel_agent.understanding import complete_form

T1 = {"persona_id": "T1", "usual_party": 1, "accessibility_needs": "none"}
T3 = {"persona_id": "T3", "usual_party": 4, "accessibility_needs": "step-free hotel with lift"}


def form(**fields):
    base = {"destination": None, "destination_flexible": False, "start_date": None, "end_date": None,
            "party": None, "budget_total": None, "budget_includes": [], "budget_mentioned_without_number": False,
            "hotel_requirements": [], "min_activities_per_day": None, "other_wishes": ""}
    base.update(fields)
    return base


def test_complete_request_is_planned():
    result = complete_form(form(destination="LIS", start_date="2026-11-13", end_date="2026-11-16",
                                party=1, budget_total=450, budget_includes=["flights", "hotel"],
                                hotel_requirements=["free_cancellation"]), T1)
    assert result["decision"] == "PLAN"
    assert result["missing"] == []
    assert result["constraints"]["budget_includes"] == ["flights", "hotel"]


def test_missing_dates_means_ask():
    result = complete_form(form(destination_flexible=True, budget_total=800), T1)
    assert result["decision"] == "ASK"
    assert result["missing"] == ["start_date", "end_date"]


def test_flexible_destination_is_not_asked():
    result = complete_form(form(destination_flexible=True, start_date="2026-11-13", end_date="2026-11-16"), T1)
    assert result["decision"] == "PLAN"


def test_missing_destination_means_ask():
    result = complete_form(form(start_date="2026-11-13", end_date="2026-11-16"), T1)
    assert result["missing"] == ["destination"]


def test_budget_hint_without_number_means_ask():
    result = complete_form(form(destination="PRG", start_date="2026-11-14", end_date="2026-11-16",
                                budget_mentioned_without_number=True), T1)
    assert result["missing"] == ["budget"]


def test_invalid_date_counts_as_missing():
    result = complete_form(form(destination="LIS", start_date="13 November", end_date="2026-11-16"), T1)
    assert result["missing"] == ["start_date"]


def test_date_outside_data_period_counts_as_missing():
    # R06 test run: the model turned "after the 20th" into 20 April
    result = complete_form(form(start_date="2026-04-20", destination_flexible=True, end_date="2026-11-25"), T1)
    assert result["missing"] == ["start_date"]


def test_messy_budget_scope_means_everything():
    # R08 test run: the model returned ["hotel", "hotel"]
    result = complete_form(form(destination="PRG", start_date="2026-11-14", end_date="2026-11-16",
                                budget_total=300, budget_includes=["hotel", "hotel"]), T1)
    assert result["constraints"]["budget_includes"] == ["flights", "hotel", "activities"]


def test_party_and_accessibility_come_from_persona():
    result = complete_form(form(destination="AMS", start_date="2026-11-06", end_date="2026-11-08"), T3)
    assert result["constraints"]["party"] == 4
    assert result["constraints"]["hotel_requirements"] == ["step_free_with_elevator"]


def test_budget_without_scope_covers_everything():
    result = complete_form(form(destination="AMS", start_date="2026-11-06", end_date="2026-11-08", budget_total=1500), T3)
    assert result["constraints"]["budget_includes"] == ["flights", "hotel", "activities"]
