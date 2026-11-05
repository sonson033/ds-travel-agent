"""Mock travel tools built from the delivered data, including their failures.

Failure rates and the random seed come from data/fault_config.json, so every run
with the same seed produces the same sequence of timeouts and empty results.
"""

import copy
import random
from datetime import datetime, timedelta

from travel_agent import config
from travel_agent.data import load_calendar, load_json


class ToolTimeout(Exception):
    """The tool did not answer in time. The result is unknown, not empty."""


class BookingFailed(Exception):
    """The booking system rejected the booking. Nothing was booked."""


class TravelTools:
    """All mock tools share one random generator and one call log.

    seed:        overrides the seed from fault_config.json
    fault_rates: overrides the rates from fault_config.json ({} = no failures)
    """

    def __init__(self, seed=None, fault_rates=None):
        fault_config = load_json(config.FAULT_CONFIG_FILE)
        self._rng = random.Random(fault_config["seed"] if seed is None else seed)
        self._fault_rates = fault_config["tools"] if fault_rates is None else fault_rates
        self._flights = load_json(config.FLIGHTS_FILE)
        self._booking_prices = load_json(config.FLIGHT_BOOKING_PRICES_FILE)
        self._hotels_listing = load_json(config.HOTELS_LISTING_FILE)
        self._hotels_details = {h["hotel_id"]: h for h in load_json(config.HOTELS_DETAILS_FILE)}
        self._activities = load_json(config.ACTIVITIES_FILE)
        self._weather = {(w["city"], w["date"]): w for w in load_json(config.WEATHER_FILE)}
        self._calendars = {p["persona_id"]: load_calendar(p["persona_id"])
                           for p in load_json(config.PERSONAS_FILE)}
        self.call_log = []
        self.bookings = {}  # booking_id -> simulated booking

    def _start_call(self, tool, args):
        """Log the call and decide its fault.

        Raises ToolTimeout or BookingFailed; returns True if the result must be empty.
        """
        rates = self._fault_rates.get(tool, {})
        timeout_rate = rates.get("timeout_rate", 0)
        empty_rate = rates.get("empty_result_rate", 0)
        fail_rate = rates.get("fail_rate", 0)
        roll = self._rng.random()
        if roll < timeout_rate:
            outcome = "timeout"
        elif roll < timeout_rate + empty_rate:
            outcome = "empty"
        elif roll < timeout_rate + empty_rate + fail_rate:
            outcome = "failed"
        else:
            outcome = "ok"
        self.call_log.append({"tool": tool, "args": args, "outcome": outcome})
        if outcome == "timeout":
            raise ToolTimeout(f"{tool} timed out")
        if outcome == "failed":
            raise BookingFailed(f"{tool} failed")
        return outcome == "empty"

    def search_flights(self, origin, destination, date):
        """Flights from origin to destination departing on date (YYYY-MM-DD), earliest first.

        Prices are search prices; the booking price can be higher.
        """
        if self._start_call("flight_search", {"origin": origin, "destination": destination, "date": date}):
            return []
        found = [
            dict(f) for f in self._flights
            if f["origin"] == origin and f["destination"] == destination and f["depart"].startswith(date)
        ]
        return sorted(found, key=lambda f: f["depart"])

    def get_booking_price(self, flight_id):
        """Price from the booking system for one flight; can be higher than the search price.

        Returns None if the booking system gives no price (empty result).
        """
        if self._start_call("flight_booking_price", {"flight_id": flight_id}):
            return None
        if flight_id not in self._booking_prices:
            raise ValueError(f"unknown flight_id: {flight_id}")
        return {"flight_id": flight_id, "booking_price": self._booking_prices[flight_id], "currency": "EUR"}

    def search_hotels(self, city):
        """Hotel listings in a city (airport code, e.g. "AMS"), cheapest first.

        Listing data only; it can contradict the details (price, step-free, cancellation).
        """
        if self._start_call("hotel_listing", {"city": city}):
            return []
        found = [copy.deepcopy(h) for h in self._hotels_listing if h["city"] == city]
        return sorted(found, key=lambda h: h["price_per_night"])

    def get_hotel_details(self, hotel_id):
        """Detail record for one hotel. Returns None if the system gives no details (empty result)."""
        if self._start_call("hotel_details", {"hotel_id": hotel_id}):
            return None
        if hotel_id not in self._hotels_details:
            raise ValueError(f"unknown hotel_id: {hotel_id}")
        return dict(self._hotels_details[hotel_id])

    def search_activities(self, city):
        """Activities in a city with opening hours per weekday ("closed" on closing days).

        An empty list can be a tool failure: every city in the data has activities.
        """
        if self._start_call("activity_search", {"city": city}):
            return []
        return [copy.deepcopy(a) for a in self._activities if a["city"] == city]

    def get_weather(self, city, date):
        """Weather forecast for one city and day (YYYY-MM-DD).

        Returns None if there is no forecast (date or city not covered, or empty result).
        """
        if self._start_call("weather", {"city": city, "date": date}):
            return None
        forecast = self._weather.get((city, date))
        return dict(forecast) if forecast else None

    def check_calendar(self, persona_id, start_date, end_date):
        """Calendar events of a traveller that overlap the days start_date to end_date (YYYY-MM-DD, inclusive)."""
        self._start_call("calendar", {"persona_id": persona_id, "start_date": start_date, "end_date": end_date})
        if persona_id not in self._calendars:
            raise ValueError(f"unknown persona_id: {persona_id}")
        range_start = datetime.fromisoformat(start_date)  # midnight
        range_end = datetime.fromisoformat(end_date) + timedelta(days=1)
        return [
            {"start": ev["start"].isoformat(timespec="minutes"), "end": ev["end"].isoformat(timespec="minutes"),
             "summary": ev["summary"]}
            for ev in sorted(self._calendars[persona_id], key=lambda e: e["start"])
            if ev["start"] < range_end and ev["end"] > range_start
        ]

    def prepare_booking(self, persona_id, flight_ids, party, hotel_id=None, nights=0, activity_ids=()):
        """Price a trip and hold it for confirmation. Nothing is booked yet.

        The total is computed here from booking prices (per person), the higher of the
        two hotel prices (per room and night) and activity prices (per person), never taken from the caller.
        """
        self._start_call("prepare_booking", {"persona_id": persona_id, "flight_ids": flight_ids, "party": party,
                                             "hotel_id": hotel_id, "nights": nights, "activity_ids": list(activity_ids)})
        if persona_id not in self._calendars:
            raise ValueError(f"unknown persona_id: {persona_id}")
        items = []
        for flight_id in flight_ids:
            if flight_id not in self._booking_prices:
                raise ValueError(f"unknown flight_id: {flight_id}")
            price = self._booking_prices[flight_id]
            items.append({"type": "flight", "id": flight_id, "unit_price": price, "quantity": party,
                          "price": price * party})
        if hotel_id is not None:
            if hotel_id not in self._hotels_details:
                raise ValueError(f"unknown hotel_id: {hotel_id}")
            listing = next(h for h in self._hotels_listing if h["hotel_id"] == hotel_id)
            price = max(listing["price_per_night"], self._hotels_details[hotel_id]["price_per_night"])
            items.append({"type": "hotel", "id": hotel_id, "unit_price": price, "quantity": nights,
                          "price": price * nights})
        activities = {a["activity_id"]: a for a in self._activities}
        for activity_id in activity_ids:
            if activity_id not in activities:
                raise ValueError(f"unknown activity_id: {activity_id}")
            price = activities[activity_id]["price"]
            items.append({"type": "activity", "id": activity_id, "unit_price": price, "quantity": party,
                          "price": price * party})
        booking_id = f"BK-{len(self.bookings) + 1:03d}"
        self.bookings[booking_id] = {
            "booking_id": booking_id, "persona_id": persona_id, "items": items,
            "total_price": sum(i["price"] for i in items), "currency": "EUR",
            "status": "awaiting_confirmation",
        }
        return copy.deepcopy(self.bookings[booking_id])

    def confirm_booking(self, booking_id):
        """Book a prepared trip (simulated).

        Only call this from application code after the user explicitly said yes.
        Never give this tool to the language model. On BookingFailed nothing is booked
        and the booking stays awaiting confirmation.
        """
        if booking_id not in self.bookings:
            raise ValueError(f"unknown booking_id: {booking_id}")
        if self.bookings[booking_id]["status"] != "awaiting_confirmation":
            raise ValueError(f"booking {booking_id} is already {self.bookings[booking_id]['status']}")
        self._start_call("booking", {"booking_id": booking_id})
        self.bookings[booking_id]["status"] = "confirmed"
        return copy.deepcopy(self.bookings[booking_id])
