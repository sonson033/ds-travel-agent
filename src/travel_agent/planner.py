"""Planner: builds the cheapest plan that meets the constraints, using only the mock tools.

The planner never looks at the data directly and never asks the checker: it only knows what
the (unreliable) tools told it. Timeouts and empty results are retried; what stays unknown is
reported, never guessed.
"""

from datetime import date, datetime, timedelta

from travel_agent.checker import HOTEL_REQUIREMENTS, MIN_BUFFER, RAIN_WARNING_PROB, WEEKDAYS
from travel_agent.tools import ToolTimeout
from travel_agent.understanding import CITY_CODES

MAX_ATTEMPTS = 3  # per tool call: first try + 2 retries


class Planner:
    def __init__(self, tools, personas):
        self.tools = tools
        self.personas = {p["persona_id"]: p for p in personas}

    def _call(self, tool, *args, retry_if_empty=False):
        """Call a tool, retrying timeouts (and empty results if asked). Returns (result, answered)."""
        result = None
        for _ in range(MAX_ATTEMPTS):
            try:
                result = tool(*args)
            except ToolTimeout:
                continue
            if retry_if_empty and not result:
                continue
            return result, True
        # after all retries: an empty list is an answer ("nothing found"); None (timeout, no price) stays unknown
        return result, result is not None

    def plan(self, persona_id, constraints):
        """Return {"status": "PLAN" | "DECLINE", "plan", "total_price", "reasons", "warnings", "failures"}."""
        self.failures, self.warnings = [], []
        home = self.personas[persona_id]["home_airport"]
        start, end = constraints["start_date"], constraints["end_date"]
        nights = (date.fromisoformat(end) - date.fromisoformat(start)).days
        events, _ = self._call(self.tools.check_calendar, persona_id, start, end)
        destinations = [constraints["destination"]] if constraints.get("destination") else CITY_CODES

        options, reasons = [], []
        for dest in destinations:
            option, reason = self._best_option(persona_id, home, dest, start, end, nights, constraints, events)
            if option:
                options.append(option)
            else:
                reasons.append(f"{dest}: {reason}")
        if not options:
            return self._result("DECLINE", None, reasons)

        best = min(options, key=lambda o: o["total_price"])
        budget = constraints.get("budget_total")
        if budget is not None and best["total_price"] > budget:
            return self._result("DECLINE", best,
                                [f"cheapest possible plan costs {best['total_price']:.0f} EUR, budget is {budget:.0f} EUR"])
        self.warnings += best["warnings"]
        return self._result("PLAN", best, [])

    def _result(self, status, option, reasons):
        option = option or {}
        return {"status": status, "plan": option.get("plan"), "summary": option.get("summary"),
                "total_price": option.get("total_price"), "reasons": reasons,
                "warnings": self.warnings, "failures": self.failures}

    # --- flights ---------------------------------------------------------------

    def _flights(self, origin, destination, day, party, excluded=()):
        """Flights with enough seats and a confirmed booking price, as (flight, booking_price)."""
        found, answered = self._call(self.tools.search_flights, origin, destination, day, retry_if_empty=True)
        if not answered:
            self.failures.append(f"flight search {origin}->{destination} {day} timed out {MAX_ATTEMPTS} times")
            return None
        priced = []
        for flight in found:
            if flight["seats_left"] < party or flight["flight_id"] in excluded:
                continue
            price, answered = self._call(self.tools.get_booking_price, flight["flight_id"], retry_if_empty=True)
            if not answered:
                self.failures.append(f"no booking price for {flight['flight_id']}; flight skipped")
                continue
            priced.append((flight, price["booking_price"]))
        return priced

    def _calendar_problem(self, outbound, return_flight, events):
        """'conflict', 'tight' (gap below MIN_BUFFER before departure) or None."""
        away_from = datetime.fromisoformat(outbound["depart"])
        away_until = datetime.fromisoformat(return_flight["arrive"])
        problem = None
        for ev in events or []:
            ev_start, ev_end = datetime.fromisoformat(ev["start"]), datetime.fromisoformat(ev["end"])
            if ev_start < away_until and ev_end > away_from:
                return "conflict", ev
            if ev_end <= away_from and away_from - ev_end < MIN_BUFFER:
                problem = ("tight", ev)
        return problem or (None, None)

    # --- hotels ----------------------------------------------------------------

    def _hotels(self, city, requirements, excluded=()):
        """Hotels meeting all requirements in both sources, cheapest first."""
        listings, answered = self._call(self.tools.search_hotels, city)
        if not answered:
            self.failures.append(f"hotel search {city} timed out {MAX_ATTEMPTS} times")
            return None
        usable = []
        for listing in listings:
            if listing["hotel_id"] in excluded:
                continue
            details, answered = self._call(self.tools.get_hotel_details, listing["hotel_id"], retry_if_empty=True)
            if not answered:
                self.failures.append(f"no details for {listing['hotel_id']}; hotel skipped (requirements unverified)")
                continue
            ok = True
            for req in requirements:
                listing_check, details_check = HOTEL_REQUIREMENTS[req]
                answers = [a for a in (listing_check(listing), details_check(details)) if a is not None]
                if not answers or not all(answers):
                    ok = False
            if ok:
                usable.append({"hotel_id": listing["hotel_id"], "name": listing["name"], "stars": listing["stars"],
                               "price_per_night": max(listing["price_per_night"], details["price_per_night"]),
                               "cancellation_policy": details["cancellation_policy"]})
        return sorted(usable, key=lambda h: h["price_per_night"])

    # --- combine ---------------------------------------------------------------

    def _best_option(self, persona_id, home, dest, start, end, nights, constraints, events):
        """Cheapest flights + hotel for one destination, or (None, reason)."""
        party = constraints["party"]
        excluded_flights = constraints.get("excluded_flights", [])
        outbound = self._flights(home, dest, start, party, excluded_flights)
        return_flights = self._flights(dest, home, end, party, excluded_flights)
        if outbound is None or return_flights is None:
            return None, "flight search unavailable (tool failures)"
        if not outbound or not return_flights:
            return None, "no flights with enough seats on these dates"

        pairs, conflicts = [], []
        for (out, out_price), (ret, ret_price) in ((o, r) for o in outbound for r in return_flights):
            problem, event = self._calendar_problem(out, ret, events)
            if problem == "conflict":
                conflicts.append(f"{out['flight_id']} clashes with '{event['summary']}'")
                continue
            warning = (f"only a short gap between '{event['summary']}' and departure {out['flight_id']}; ask the traveller"
                       if problem == "tight" else None)
            pairs.append((party * (out_price + ret_price), out, ret, warning, out_price, ret_price))
        if not pairs:
            return None, "every flight combination clashes with the calendar: " + "; ".join(sorted(set(conflicts)))

        hotels = self._hotels(dest, constraints.get("hotel_requirements", []), constraints.get("excluded_hotels", []))
        if hotels is None:
            return None, "hotel search unavailable (tool failures)"
        if not hotels:
            return None, "no hotel meets the requirements in both sources"

        activities, activity_price, activity_warnings, activity_summary = [], 0, [], []
        if constraints.get("min_activities_per_day", 0) > 0:
            picked = self._activities(dest, start, end, constraints)
            if picked is None:
                return None, "activity search unavailable (tool failures)"
            activities, activity_price, activity_warnings, activity_summary = picked
            activity_price *= party
            if "activities" not in constraints.get("budget_includes", []):
                activity_price = 0

        flight_price, out, ret, warning, out_price, ret_price = min(pairs, key=lambda p: p[0])
        hotel = hotels[0]
        plan = {"persona_id": persona_id, "party": party, "destination": dest, "start_date": start, "end_date": end,
                "flights": {"outbound": out["flight_id"], "return": ret["flight_id"]},
                "hotel": {"hotel_id": hotel["hotel_id"], "nights": nights}, "activities": activities}
        summary = {  # what the tools told us, for writing the reply
            "outbound": {**{k: out[k] for k in ("flight_id", "depart", "arrive", "stops")}, "price_per_person": out_price},
            "return": {**{k: ret[k] for k in ("flight_id", "depart", "arrive", "stops")}, "price_per_person": ret_price},
            "hotel": {**hotel, "nights": nights},
            "activities": activity_summary,
        }
        return {"plan": plan, "summary": summary, "total_price": flight_price + nights * hotel["price_per_night"] + activity_price,
                "warnings": ([warning] if warning else []) + activity_warnings}, None

    # --- activities ------------------------------------------------------------

    def _activities(self, city, start, end, constraints):
        """Pick activities for every full day: open that day, indoor if rain/storm/unknown weather, cheapest first.

        Returns (activities, price per person, warnings, summary), or None if the activity search failed.
        """
        found, answered = self._call(self.tools.search_activities, city, retry_if_empty=True)
        if not answered or not found:
            # every city has activities, so empty after all retries is a tool failure
            self.failures.append(f"activity search {city} returned nothing {MAX_ATTEMPTS} times")
            return None
        no_outdoor = set(constraints.get("no_outdoor_dates", []))
        per_day = constraints["min_activities_per_day"]
        picked, price, warnings, used, summary = [], 0, [], set(), []
        day = date.fromisoformat(start) + timedelta(days=1)
        while day < date.fromisoformat(end):
            iso, weekday = day.isoformat(), WEEKDAYS[day.weekday()]
            forecast, answered = self._call(self.tools.get_weather, city, iso, retry_if_empty=True)
            if not answered:
                self.failures.append(f"no weather for {city} {iso}; planned indoor to be safe")
            wet = not answered or forecast["precipitation_prob"] >= RAIN_WARNING_PROB
            candidates = [a for a in found
                          if a["activity_id"] not in used and a["opening_hours"][weekday] != "closed"
                          and not (a["outdoor"] and iso in no_outdoor)]
            candidates.sort(key=lambda a: (a["outdoor"] and wet, a["price"], a["activity_id"]))
            for activity in candidates[:per_day]:
                used.add(activity["activity_id"])
                picked.append({"activity_id": activity["activity_id"], "date": iso})
                summary.append({"activity_id": activity["activity_id"], "name": activity["name"], "date": iso,
                                "outdoor": activity["outdoor"], "price_per_person": activity["price"]})
                price += activity["price"]
                if activity["price"] == 0:
                    warnings.append(f"{activity['activity_id']} ({activity['name']}) is listed at 0 EUR: free or unknown")
            day += timedelta(days=1)
        return picked, price, warnings, summary

    def forecast(self, city, start, end):
        """Weather for every day of the trip as told by the tool; None where the tool gave no answer."""
        days, day = [], date.fromisoformat(start)
        while day <= date.fromisoformat(end):
            weather, answered = self._call(self.tools.get_weather, city, day.isoformat(), retry_if_empty=True)
            days.append({"date": day.isoformat(), "condition": weather["condition"], "rain_prob": weather["precipitation_prob"],
                         "temp_c": weather["temp_c"]} if answered else {"date": day.isoformat(), "condition": None})
            day += timedelta(days=1)
        return days
