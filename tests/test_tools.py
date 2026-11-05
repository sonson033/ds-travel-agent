import pytest

from travel_agent.tools import BookingFailed, ToolTimeout, TravelTools


def no_faults():
    return TravelTools(fault_rates={})


def test_search_flights_finds_matching_flights_sorted():
    flights = no_faults().search_flights("BER", "LIS", "2026-11-13")
    assert [f["flight_id"] for f in flights] == ["FL-0002", "FL-0001", "FL-0003"]


def test_search_flights_returns_search_price_not_booking_price():
    flights = no_faults().search_flights("BER", "LIS", "2026-11-13")
    fl_0003 = next(f for f in flights if f["flight_id"] == "FL-0003")
    assert fl_0003["price"] == 72.0  # booking price is 82.0


def test_search_flights_without_flights_returns_empty_list():
    assert no_faults().search_flights("BER", "LIS", "2026-11-14") == []


def test_results_are_copies():
    tools = no_faults()
    tools.search_flights("BER", "LIS", "2026-11-13")[0]["price"] = 0
    assert tools.search_flights("BER", "LIS", "2026-11-13")[0]["price"] > 0


def test_forced_timeout_raises():
    tools = TravelTools(fault_rates={"flight_search": {"timeout_rate": 1.0}})
    with pytest.raises(ToolTimeout):
        tools.search_flights("BER", "LIS", "2026-11-13")
    assert tools.call_log[-1]["outcome"] == "timeout"


def test_forced_empty_result_returns_empty_list():
    tools = TravelTools(fault_rates={"flight_search": {"empty_result_rate": 1.0}})
    assert tools.search_flights("BER", "LIS", "2026-11-13") == []
    assert tools.call_log[-1]["outcome"] == "empty"


def outcomes(tools, n=200):
    for _ in range(n):
        try:
            tools.search_flights("BER", "LIS", "2026-11-13")
        except ToolTimeout:
            pass
    return [c["outcome"] for c in tools.call_log]


def test_faults_are_reproducible_with_the_same_seed():
    first, second = outcomes(TravelTools()), outcomes(TravelTools())
    assert first == second
    assert "timeout" in first and "empty" in first and "ok" in first


def test_different_seed_gives_different_faults():
    assert outcomes(TravelTools()) != outcomes(TravelTools(seed=1))


def test_booking_price_can_differ_from_search_price():
    tools = no_faults()
    assert tools.get_booking_price("FL-0003")["booking_price"] == 82.0  # search price 72.0
    assert tools.get_booking_price("FL-0001")["booking_price"] == 58.0  # same as search


def test_booking_price_unknown_flight_raises():
    with pytest.raises(ValueError):
        no_faults().get_booking_price("FL-9999")


def test_booking_price_forced_timeout_raises():
    tools = TravelTools(fault_rates={"flight_booking_price": {"timeout_rate": 1.0}})
    with pytest.raises(ToolTimeout):
        tools.get_booking_price("FL-0003")


def test_booking_price_forced_empty_returns_none():
    tools = TravelTools(fault_rates={"flight_booking_price": {"empty_result_rate": 1.0}})
    assert tools.get_booking_price("FL-0003") is None


def test_search_hotels_returns_city_hotels_cheapest_first():
    hotels = no_faults().search_hotels("AMS")
    assert len(hotels) == 11
    assert all(h["city"] == "AMS" for h in hotels)
    prices = [h["price_per_night"] for h in hotels]
    assert prices == sorted(prices)


def test_search_hotels_unknown_city_returns_empty_list():
    assert no_faults().search_hotels("XXX") == []


def test_hotel_sources_contradict_each_other():
    tools = no_faults()
    listing = next(h for h in tools.search_hotels("AMS") if h["hotel_id"] == "HT-086")
    details = tools.get_hotel_details("HT-086")
    assert listing["accessibility"]["step_free"] is True
    assert details["step_free_entrance"] is False


def test_hotel_listing_results_are_deep_copies():
    tools = no_faults()
    tools.search_hotels("AMS")[0]["accessibility"]["step_free"] = "changed"
    assert tools.search_hotels("AMS")[0]["accessibility"]["step_free"] != "changed"


def test_hotel_details_unknown_hotel_raises():
    with pytest.raises(ValueError):
        no_faults().get_hotel_details("HT-999")


def test_hotel_details_forced_timeout_raises():
    tools = TravelTools(fault_rates={"hotel_details": {"timeout_rate": 1.0}})
    with pytest.raises(ToolTimeout):
        tools.get_hotel_details("HT-086")


def test_search_activities_returns_city_activities_with_opening_hours():
    activities = no_faults().search_activities("BCN")
    assert len(activities) == 10
    food_tour = next(a for a in activities if a["activity_id"] == "AC-011")
    assert food_tour["opening_hours"]["Mon"] == "closed"


def test_search_activities_forced_empty_returns_empty_list():
    tools = TravelTools(fault_rates={"activity_search": {"empty_result_rate": 1.0}})
    assert tools.search_activities("BCN") == []
    assert tools.call_log[-1]["outcome"] == "empty"


def test_get_weather_returns_forecast_for_the_day():
    forecast = no_faults().get_weather("BCN", "2026-11-21")
    assert forecast["condition"] == "sunny"  # D3 reports a storm for this day
    assert forecast["precipitation_prob"] == 0.11


def test_get_weather_outside_data_returns_none():
    tools = no_faults()
    assert tools.get_weather("BCN", "2026-12-01") is None
    assert tools.get_weather("XXX", "2026-11-21") is None


def test_get_weather_forced_timeout_raises():
    tools = TravelTools(fault_rates={"weather": {"timeout_rate": 1.0}})
    with pytest.raises(ToolTimeout):
        tools.get_weather("BCN", "2026-11-21")


def test_check_calendar_finds_workshop_on_departure_day():
    events = no_faults().check_calendar("T1", "2026-11-13", "2026-11-16")
    assert events == [{"start": "2026-11-13T12:00", "end": "2026-11-13T17:00",
                       "summary": "Team workshop (Berlin office)"}]


def test_check_calendar_includes_all_day_event_on_single_day():
    events = no_faults().check_calendar("T1", "2026-11-20", "2026-11-20")
    assert [e["summary"] for e in events] == ["Project delivery deadline"]


def test_check_calendar_free_period_returns_empty_list():
    assert no_faults().check_calendar("T2", "2026-11-20", "2026-11-23") == []


def test_check_calendar_unknown_persona_raises():
    with pytest.raises(ValueError):
        no_faults().check_calendar("T9", "2026-11-13", "2026-11-16")


def test_check_calendar_never_fails_and_is_logged():
    tools = TravelTools()  # calendar is not in fault_config.json
    for _ in range(100):
        tools.check_calendar("T3", "2026-11-06", "2026-11-08")
    assert {c["outcome"] for c in tools.call_log} == {"ok"}
    assert len(tools.call_log) == 100


def prepare_r01(tools):
    return tools.prepare_booking("T1", ["FL-0003", "FL-0004"], party=1, hotel_id="HT-081", nights=3)


def test_prepare_booking_computes_total_from_booking_prices():
    booking = prepare_r01(no_faults())
    assert booking["total_price"] == 82.0 + 65.0 + 3 * 68.0  # 351, FL-0003 at booking price
    assert booking["status"] == "awaiting_confirmation"


def test_prepare_booking_does_not_book():
    tools = no_faults()
    booking = prepare_r01(tools)
    assert tools.bookings[booking["booking_id"]]["status"] == "awaiting_confirmation"


def test_prepare_booking_uses_higher_hotel_price_and_party_size():
    booking = no_faults().prepare_booking("T2", ["FL-0001"], party=2, hotel_id="HT-005", nights=1)
    assert booking["total_price"] == 2 * 58.0 + 134.0  # HT-005: listing 117, details 134


def test_prepare_booking_includes_activities_per_person():
    booking = no_faults().prepare_booking("T2", ["FL-0008", "FL-0010"], party=2, hotel_id="HT-083", nights=3,
                                          activity_ids=["AC-016", "AC-017"])
    assert booking["total_price"] == 2 * (69 + 74) + 3 * 58 + 2 * (8 + 8)  # 492, same as the planner


def test_prepare_booking_unknown_flight_raises():
    with pytest.raises(ValueError):
        no_faults().prepare_booking("T1", ["FL-9999"], party=1)


def test_confirm_booking_books():
    tools = no_faults()
    booking_id = prepare_r01(tools)["booking_id"]
    assert tools.confirm_booking(booking_id)["status"] == "confirmed"


def test_confirm_booking_twice_raises():
    tools = no_faults()
    booking_id = prepare_r01(tools)["booking_id"]
    tools.confirm_booking(booking_id)
    with pytest.raises(ValueError):
        tools.confirm_booking(booking_id)


def test_confirm_unknown_booking_raises():
    with pytest.raises(ValueError):
        no_faults().confirm_booking("BK-999")


def test_failed_booking_books_nothing_and_can_be_retried():
    tools = TravelTools(fault_rates={"booking": {"fail_rate": 1.0}})
    booking_id = prepare_r01(tools)["booking_id"]
    with pytest.raises(BookingFailed):
        tools.confirm_booking(booking_id)
    assert tools.bookings[booking_id]["status"] == "awaiting_confirmation"
    assert tools.call_log[-1]["outcome"] == "failed"


def test_tool_names_match_fault_config():
    rates = TravelTools()._fault_rates
    for tool in ["flight_search", "flight_booking_price", "hotel_listing", "hotel_details",
                 "activity_search", "weather", "booking"]:
        assert tool in rates
