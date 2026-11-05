"""Plan checker: tests a plan against the hard constraints.

The checker is the referee. It reads the data directly (no tool failures) and never
trusts prices or facts written into the plan; the plan only holds IDs and dates.
"""

from datetime import date, datetime, timedelta

from travel_agent import config
from travel_agent.data import load_calendar, load_json

REQUIRED_FIELDS = ["persona_id", "party", "destination", "start_date", "end_date", "flights"]
MIN_BUFFER = timedelta(hours=2)  # below this gap between an event and departure: warning
RAIN_WARNING_PROB = 0.5  # outdoor activity on a day with at least this rain probability: warning
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _issue(rule, message):
    return {"rule": rule, "message": message}


# Hotel requirement -> (what the listing says, what the details say); None = source has no such field
HOTEL_REQUIREMENTS = {
    "free_cancellation": (lambda l: l["cancellation_policy"] == "free_cancellation",
                          lambda d: d["cancellation_policy"] == "free_cancellation"),
    "step_free_with_elevator": (lambda l: l["accessibility"]["step_free"] and l["accessibility"]["elevator"],
                                lambda d: d["step_free_entrance"] and d["elevator"]),
    "breakfast": (lambda l: "breakfast" in l["amenities"],
                  lambda d: d["breakfast_included"]),
    "min_stars_4": (lambda l: l["stars"] >= 4,
                    lambda d: None),
}


class PlanChecker:
    def __init__(self):
        self._flights = {f["flight_id"]: f for f in load_json(config.FLIGHTS_FILE)}
        self._booking_prices = load_json(config.FLIGHT_BOOKING_PRICES_FILE)
        self._hotels_listing = {h["hotel_id"]: h for h in load_json(config.HOTELS_LISTING_FILE)}
        self._hotels_details = {h["hotel_id"]: h for h in load_json(config.HOTELS_DETAILS_FILE)}
        self._activities = {a["activity_id"]: a for a in load_json(config.ACTIVITIES_FILE)}
        self._weather = {(w["city"], w["date"]): w for w in load_json(config.WEATHER_FILE)}
        self._home = {p["persona_id"]: p["home_airport"] for p in load_json(config.PERSONAS_FILE)}
        self._calendars = {pid: load_calendar(pid) for pid in self._home}

    def check(self, plan, constraints):
        """Return {"valid", "violations", "warnings", "total_price"} for a plan and the traveller's constraints."""
        violations, warnings = [], []
        missing = [f for f in REQUIRED_FIELDS if f not in plan]
        if missing:
            violations.append(_issue("missing_field", f"plan is missing: {', '.join(missing)}"))
            return self._result(violations, warnings, None)
        if plan["persona_id"] not in self._home:
            violations.append(_issue("unknown_persona", f"unknown persona_id {plan['persona_id']!r}"))
            return self._result(violations, warnings, None)

        self._check_matches_request(plan, constraints, violations)
        used = list(plan["flights"].values()) + [plan.get("hotel", {}).get("hotel_id")]
        for item in used:
            if item in constraints.get("excluded_flights", []) + constraints.get("excluded_hotels", []):
                violations.append(_issue("excluded_item_used", f"{item} is no longer available (cancelled or sold out)"))
        legs = self._check_flights(plan, violations)
        if "outbound" in legs and "return" in legs:
            self._check_calendar(plan, legs["outbound"], legs["return"], violations, warnings)
        hotel_price = self._check_hotel(plan, constraints, violations)
        activity_price = self._check_activities(plan, constraints, violations, warnings)

        flight_price = sum(self._booking_prices[f["flight_id"]] * plan["party"] for f in legs.values())
        total_price = flight_price + hotel_price
        if "activities" in constraints.get("budget_includes", []):
            total_price += activity_price
        budget = constraints.get("budget_total")
        if budget is not None and total_price > budget:
            violations.append(_issue("over_budget", f"total {total_price:.0f} EUR exceeds budget {budget:.0f} EUR"))
        return self._result(violations, warnings, total_price)

    def _result(self, violations, warnings, total_price):
        return {"valid": not violations, "violations": violations, "warnings": warnings, "total_price": total_price}

    def _check_matches_request(self, plan, constraints, violations):
        for field in ["destination", "party", "start_date", "end_date"]:
            wanted = constraints.get(field)
            if wanted is not None and plan[field] != wanted:
                violations.append(_issue(f"{field}_mismatch", f"plan has {field} {plan[field]!r}, request wants {wanted!r}"))

    def _check_flights(self, plan, violations):
        """Check both legs; return the flight records that exist, keyed by leg."""
        home, dest = self._home[plan["persona_id"]], plan["destination"]
        expected = {
            "outbound": (home, dest, plan["start_date"]),
            "return": (dest, home, plan["end_date"]),
        }
        legs = {}
        for leg, (origin, destination, day) in expected.items():
            flight_id = plan["flights"].get(leg)
            flight = self._flights.get(flight_id)
            if flight is None:
                violations.append(_issue("unknown_flight", f"{leg} flight {flight_id!r} does not exist"))
                continue
            if (flight["origin"], flight["destination"]) != (origin, destination):
                violations.append(_issue("wrong_route", f"{leg} {flight_id} flies {flight['origin']}→{flight['destination']}, "
                                                        f"needed {origin}→{destination}"))
            if not flight["depart"].startswith(day):
                violations.append(_issue("wrong_date", f"{leg} {flight_id} departs {flight['depart']}, needed {day}"))
            if flight["seats_left"] < plan["party"]:
                violations.append(_issue("not_enough_seats", f"{leg} {flight_id} has {flight['seats_left']} seats left "
                                                             f"for {plan['party']} travellers"))
            legs[leg] = flight
        return legs

    def _check_hotel(self, plan, constraints, violations):
        """Check the hotel; return its price for the stay (higher of the two sources), 0 if unusable."""
        nights_needed = (date.fromisoformat(plan["end_date"]) - date.fromisoformat(plan["start_date"])).days
        hotel = plan.get("hotel")
        if hotel is None:
            if nights_needed > 0:
                violations.append(_issue("missing_hotel", f"trip has {nights_needed} nights but no hotel"))
            return 0
        hotel_id = hotel.get("hotel_id")
        listing, details = self._hotels_listing.get(hotel_id), self._hotels_details.get(hotel_id)
        if listing is None or details is None:
            violations.append(_issue("unknown_hotel", f"hotel {hotel_id!r} does not exist"))
            return 0
        if listing["city"] != plan["destination"]:
            violations.append(_issue("hotel_wrong_city", f"{hotel_id} is in {listing['city']}, trip goes to {plan['destination']}"))
        if hotel.get("nights") != nights_needed:
            violations.append(_issue("wrong_nights", f"{hotel_id} booked for {hotel.get('nights')} nights, "
                                                     f"trip has {nights_needed}"))
        for requirement in constraints.get("hotel_requirements", []):
            if requirement not in HOTEL_REQUIREMENTS:
                raise ValueError(f"unknown hotel requirement: {requirement}")
            listing_check, details_check = HOTEL_REQUIREMENTS[requirement]
            listing_says, details_says = listing_check(listing), details_check(details)
            answers = [a for a in (listing_says, details_says) if a is not None]
            if not any(answers):
                violations.append(_issue("hotel_requirement_not_met", f"{hotel_id} does not meet '{requirement}'"))
            elif not all(answers):
                violations.append(_issue("hotel_requirement_unconfirmed",
                                         f"{hotel_id} '{requirement}': listing says {listing_says}, details say {details_says}"))
        price_per_night = max(listing["price_per_night"], details["price_per_night"])
        return price_per_night * (hotel.get("nights") or 0)

    def _check_activities(self, plan, constraints, violations, warnings):
        """Check every planned activity; return their price for the whole party."""
        start, end = date.fromisoformat(plan["start_date"]), date.fromisoformat(plan["end_date"])
        no_outdoor = set(constraints.get("no_outdoor_dates", []))
        price, per_day = 0, {}
        for item in plan.get("activities", []):
            activity_id, day = item.get("activity_id"), item.get("date")
            activity = self._activities.get(activity_id)
            if activity is None:
                violations.append(_issue("unknown_activity", f"activity {activity_id!r} does not exist"))
                continue
            name = f"{activity_id} ({activity['name']})"
            if not day:
                violations.append(_issue("activity_without_date", f"{name} has no date"))
                continue
            problems_before = len(violations)
            if activity["city"] != plan["destination"]:
                violations.append(_issue("activity_wrong_city", f"{name} is in {activity['city']}"))
            when = date.fromisoformat(day)
            if not start <= when <= end:
                violations.append(_issue("activity_outside_trip", f"{name} on {day} is outside the trip"))
            weekday = WEEKDAYS[when.weekday()]
            if activity["opening_hours"][weekday] == "closed":
                violations.append(_issue("activity_closed", f"{name} is closed on {weekday} {day}"))
            if activity["outdoor"] and day in no_outdoor:
                violations.append(_issue("outdoor_on_blocked_day", f"{name} is outdoor, but outdoor is not possible on {day}"))
            if len(violations) == problems_before:
                per_day[day] = per_day.get(day, 0) + 1

            forecast = self._weather.get((activity["city"], day))
            if activity["outdoor"] and forecast and forecast["precipitation_prob"] >= RAIN_WARNING_PROB:
                warnings.append(_issue("outdoor_in_rain", f"{name} is outdoor; {day} forecast: {forecast['condition']}, "
                                                          f"{forecast['precipitation_prob']:.0%} rain"))
            if activity["price"] == 0:
                warnings.append(_issue("unverified_price", f"{name} has price 0 EUR: free or unknown"))
            price += activity["price"] * plan["party"]

        # Option B: only the full days between arrival and departure day need activities
        minimum = constraints.get("min_activities_per_day", 0)
        day = start + timedelta(days=1)
        while day < end:
            if per_day.get(day.isoformat(), 0) < minimum:
                violations.append(_issue("too_few_activities", f"{day.isoformat()} has {per_day.get(day.isoformat(), 0)} "
                                                               f"valid activities, needs {minimum}"))
            day += timedelta(days=1)
        return price

    def _check_calendar(self, plan, outbound, return_flight, violations, warnings):
        """No event may overlap the time away (outbound departure to return arrival)."""
        away_from = datetime.fromisoformat(outbound["depart"])
        away_until = datetime.fromisoformat(return_flight["arrive"])
        for ev in self._calendars[plan["persona_id"]]:
            if ev["start"] < away_until and ev["end"] > away_from:
                violations.append(_issue("calendar_conflict", f"trip ({away_from:%d %b %H:%M} – {away_until:%d %b %H:%M}) "
                                                              f"overlaps '{ev['summary']}' "
                                                              f"({ev['start']:%d %b %H:%M} – {ev['end']:%H:%M})"))
            elif timedelta(0) <= away_from - ev["end"] < MIN_BUFFER:
                gap = int((away_from - ev["end"]).total_seconds() // 60)
                warnings.append(_issue("tight_schedule", f"only {gap} min between '{ev['summary']}' and "
                                                         f"departure {outbound['flight_id']}"))
