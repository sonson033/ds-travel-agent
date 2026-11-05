"""The travel agent: one conversation from a free-text request to a plan, a question or an honest no.

Language model: fills in the form (understanding.py) and writes the reply.
Code: decides whether to ask (fixed rules), plans (planner.py), never books on its own.
"""

import json
import re

import ollama

from travel_agent import config
from travel_agent.data import load_json
from travel_agent.planner import Planner
from travel_agent.tools import BookingFailed, TravelTools
from travel_agent.understanding import complete_form, fill_form

MAX_QUESTIONS = 3  # BRIEF.md: at most 3 clarifying questions before the first draft plan
CONFIRM_WORDS = {"yes", "ja"}  # only an explicit yes books; checked by code, never by the language model

QUESTIONS = {  # fixed wording per missing field; start and end date are asked together
    "dates": "When do you want to travel (first and last day)?",
    "destination": "Where would you like to go? We can offer Lisbon, Barcelona, Amsterdam, Prague, Vienna, "
                   "Rome, Athens, Valencia, Split and Palermo - or should I pick for you?",
    "budget": "What is your maximum budget in EUR, and does it include flights, hotel and activities?",
}

CITY_NAMES = {"LIS": "Lisbon", "BCN": "Barcelona", "AMS": "Amsterdam", "PRG": "Prague", "VIE": "Vienna",
              "FCO": "Rome", "ATH": "Athens", "VLC": "Valencia", "SPU": "Split", "PMO": "Palermo"}

# PLAN: the plan details are written by code (render_plan); the model only adds this short comment.
COMMENT_PROMPT = """You add a short comment to a travel plan that is shown to the traveller.
Write 1 to 3 sentences, only about these facts: the warnings, the unverified items, and whether the weather
fits the wishes in other_wishes (e.g. say honestly if sunshine is not forecast).
If latest_update is given, it is newer than the weather forecast and always wins over it.
Do not repeat the plan, do not mention prices, flights, hotels or activities, do not invent anything.
If there is nothing to say, write: Enjoy your trip!
Answer in the language of the traveller's request."""

DECLINE_PROMPT = """You write the reply of a travel agent to a traveller. There is no plan.
Say clearly that the request cannot be met as asked and why (use the reasons in the JSON).
Then offer exactly the options listed in "options" and nothing else. Do not invent other options, amounts or
offers, and do not offer to proceed with a plan.
Keep it under 120 words. Answer in the language of the traveller's request."""


def render_plan(summary, total_price, party, budget):
    """The plan as fixed text: every flight, hotel, activity and price comes straight from the planner."""
    def flight(label, f):
        stops = "direct" if f["stops"] == 0 else f"{f['stops']} stop"
        return (f"- {label}: {f['flight_id']} on {f['depart'][:10]}, {f['depart'][11:]} -> {f['arrive'][11:]} "
                f"({stops}), {f['price_per_person']:.0f} EUR per person")
    hotel = summary["hotel"]
    lines = [flight("Outbound", summary["outbound"]), flight("Return", summary["return"]),
             f"- Hotel: {hotel['name']} ({hotel['stars']} stars), {hotel['nights']} nights at "
             f"{hotel['price_per_night']:.0f} EUR per night, cancellation: {hotel['cancellation_policy'].replace('_', ' ')}"]
    for a in summary["activities"]:
        lines.append(f"- {a['date']}: {a['name']} ({'outdoor' if a['outdoor'] else 'indoor'}), "
                     f"{a['price_per_person']:.0f} EUR per person")
    budget_text = f" (budget {budget:.0f} EUR)" if budget is not None else ""
    lines.append(f"Total for {party} traveller{'s' if party > 1 else ''}: {total_price:.0f} EUR{budget_text}")
    return "\n".join(lines)


class TravelAgent:
    def __init__(self, tools=None, client=None):
        self.personas = {p["persona_id"]: p for p in load_json(config.PERSONAS_FILE)}
        self.tools = tools or TravelTools()
        self.planner = Planner(self.tools, list(self.personas.values()))
        self.client = client or ollama.Client(host=config.OLLAMA_HOST)

    def start(self, persona_id, request_text):
        """First message of a conversation. Returns a turn dict with "status", "reply" and "state"."""
        state = {"persona_id": persona_id, "request_text": request_text, "answers": [],
                 "questions_asked": 0, "turns": 0}
        return self._step(state)

    def answer(self, state, user_text):
        """The traveller answers the agent's last questions."""
        state["answers"].append({"questions": state["last_questions"], "answer": user_text})
        return self._step(state)

    def _step(self, state):
        state["turns"] += 1
        persona = self.personas[state["persona_id"]]
        form = fill_form(self._request_with_answers(state), self.client)
        completed = complete_form(form, persona)
        state["constraints"] = completed["constraints"]

        if completed["decision"] == "ASK":
            return self._ask(state, completed["missing"])
        state["other_wishes"] = completed["other_wishes"]
        return self._plan_and_reply(state)

    def _plan_and_reply(self, state):
        persona = self.personas[state["persona_id"]]
        cons = state["constraints"]
        result = self.planner.plan(state["persona_id"], cons)
        if result["status"] == "PLAN":
            destination = result["plan"]["destination"]
            # a newer storm warning replaces the (older) forecast for that day
            weather = [{"date": d["date"], "condition": "storm warning"} if d["date"] in cons.get("no_outdoor_dates", [])
                       else d for d in self.planner.forecast(destination, cons["start_date"], cons["end_date"])]
            facts = {"warnings": result["warnings"], "unverified": result["failures"],
                     "other_wishes": state.get("other_wishes", ""), "weather": weather}
            if state.get("latest_update"):
                facts["latest_update"] = state["latest_update"]
            reply = (f"Here is your plan for {CITY_NAMES[destination]}, {cons['start_date']} to {cons['end_date']}:\n"
                     + render_plan(result["summary"], result["total_price"], cons["party"], cons["budget_total"])
                     + "\n\n" + self._write(COMMENT_PROMPT, state["request_text"], facts)
                     + "\n\nShall I prepare the booking? Nothing is booked without your explicit 'yes'.")
        else:
            facts = {"traveller": persona["name"], "budget_eur": cons["budget_total"], "reasons": result["reasons"],
                     "unverified": result["failures"], "options": ["choose other dates", "choose another destination"]}
            if result["total_price"] is not None:  # cheapest plan exists but is over budget
                facts["options"].insert(0, f"raise the budget to at least {result['total_price']:.0f} EUR")
            reply = self._write(DECLINE_PROMPT, state["request_text"], facts)
        state["plan"] = result["plan"] if result["status"] == "PLAN" else None
        return {"status": result["status"], "reply": reply, "plan": result["plan"], "total_price": result["total_price"],
                "warnings": result["warnings"], "failures": result["failures"], "state": state}

    # --- disruptions: one fixed rule per event type, then replan ----------------------

    def handle_disruption(self, state, event):
        """Change the constraints of an existing plan according to the event, then plan again.

        The message is data: it is only read for a date or a percentage, never followed as an instruction
        (e.g. "Please rebook" does not book anything).
        """
        plan = state.get("plan")
        if not plan:
            raise ValueError("there is no plan to change")
        cons = dict(state["constraints"])
        kind, message = event["event_type"], event["message"]
        if kind == "flight_cancelled":
            leg = "return" if "return" in message.lower() else "outbound"
            cons["excluded_flights"] = cons.get("excluded_flights", []) + [plan["flights"][leg]]
            change = f"flight {plan['flights'][leg]} is cancelled, so I planned without it"
        elif kind == "hotel_sold_out":
            cons["excluded_hotels"] = cons.get("excluded_hotels", []) + [plan["hotel"]["hotel_id"]]
            change = f"hotel {plan['hotel']['hotel_id']} is sold out, so I looked for another one"
        elif kind == "budget_cut":
            percent = re.search(r"(\d+)\s*(?:percent|%)", message)
            if not percent or cons.get("budget_total") is None:
                return self._cannot_handle(state, "I could not read the new budget. What is your budget now?")
            cons["budget_total"] = round(cons["budget_total"] * (1 - int(percent.group(1)) / 100), 2)
            change = f"your budget is now {cons['budget_total']:.0f} EUR"
        elif kind == "storm_forecast":
            day = re.search(r"(\d{1,2}) November", message)
            if not day:
                return self._cannot_handle(state, "On which day is the storm expected?")
            storm_day = f"2026-11-{int(day.group(1)):02d}"
            cons["no_outdoor_dates"] = cons.get("no_outdoor_dates", []) + [storm_day]
            change = f"storm warning for {storm_day}, so no outdoor activities that day"
        elif kind == "traveler_added":
            cons["party"] += 1
            change = f"one more traveller, now {cons['party']}"
        else:
            return self._cannot_handle(state, f"I don't know how to handle '{kind}'. What should I change?")
        state["constraints"] = cons
        state["latest_update"] = message
        state["turns"] += 1
        turn = self._plan_and_reply(state)
        turn["reply"] = f"Update: {change}.\n\n{turn['reply']}"
        return turn

    def _cannot_handle(self, state, question):
        state["turns"] += 1
        return {"status": "ASK", "reply": question, "state": state}

    # --- booking: prepare (agent) -> explicit "yes" (traveller) -> confirm (code) ---------

    def prepare_booking(self, state):
        """Hold the last proposed plan for confirmation and show the exact price. Nothing is booked."""
        plan = state.get("plan")
        if not plan:
            raise ValueError("there is no plan to book")
        booking = self.tools.prepare_booking(
            plan["persona_id"], [plan["flights"]["outbound"], plan["flights"]["return"]], plan["party"],
            hotel_id=plan["hotel"]["hotel_id"], nights=plan["hotel"]["nights"],
            activity_ids=[a["activity_id"] for a in plan["activities"]])
        state["booking_id"] = booking["booking_id"]
        lines = [f"- {i['type']} {i['id']}: {i['unit_price']:.0f} EUR x {i['quantity']} = {i['price']:.0f} EUR"
                 for i in booking["items"]]
        reply = (f"Booking {booking['booking_id']} is prepared but NOT booked yet:\n" + "\n".join(lines) +
                 f"\nTotal: {booking['total_price']:.0f} EUR.\nType 'yes' to book, anything else to cancel.")
        return {"status": "BOOKING_PREPARED", "reply": reply, "booking": booking, "state": state}

    def confirm_booking(self, state, user_text):
        """Book only if the traveller typed exactly 'yes' (or 'ja')."""
        booking_id = state.get("booking_id")
        if not booking_id:
            raise ValueError("there is no prepared booking")
        if user_text.strip().strip(".!").lower() not in CONFIRM_WORDS:
            return {"status": "NOT_BOOKED", "state": state,
                    "reply": f"Okay, nothing was booked. Booking {booking_id} is still waiting for your 'yes'."}
        try:
            booking = self.tools.confirm_booking(booking_id)
        except BookingFailed:
            return {"status": "BOOKING_FAILED", "state": state,
                    "reply": f"The booking system rejected booking {booking_id}. Nothing was booked. "
                             "Type 'yes' to try again."}
        return {"status": "BOOKED", "booking": booking, "state": state,
                "reply": f"Done: booking {booking_id} is confirmed. Total {booking['total_price']:.0f} EUR."}

    def _ask(self, state, missing):
        keys = []
        for field in missing:
            key = "dates" if field in ("start_date", "end_date") else field
            if key not in keys:
                keys.append(key)
        questions = [QUESTIONS[k] for k in keys][:MAX_QUESTIONS - state["questions_asked"]]
        if not questions:
            reply = ("I still cannot plan this trip because this is missing: " + ", ".join(keys) +
                     ". Please send a new request with these details.")
            return {"status": "NEED_INFO", "reply": reply, "missing": keys, "state": state}
        state["questions_asked"] += len(questions)
        state["last_questions"] = questions
        reply = "Happy to help! To plan your trip I need to know:\n" + "\n".join(
            f"{i}. {q}" for i, q in enumerate(questions, 1))
        return {"status": "ASK", "reply": reply, "questions": questions, "missing": keys, "state": state}

    def _request_with_answers(self, state):
        text = state["request_text"]
        for qa in state["answers"]:
            text += "\n\nFollow-up questions:\n" + "\n".join(qa["questions"]) + f"\nTraveller's answer: {qa['answer']}"
        return text

    def _write(self, prompt, request_text, facts):
        response = self.client.chat(
            model=config.OLLAMA_MODEL,
            messages=[{"role": "system", "content": prompt},
                      {"role": "user", "content": f"Traveller's request:\n<<<\n{request_text}\n>>>\n\n"
                                                  f"Facts:\n{json.dumps(facts, indent=1)}"}],
            options={"temperature": 0},
        )
        return response.message.content.strip()
