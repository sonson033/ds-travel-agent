"""Terminal demo of the travel agent.

Usage: python demo.py   (Ollama must be running)
Type R01-R10 to use a trip request from the data, or type your own request.
"""

from collections import Counter

from travel_agent import config
from travel_agent.agent import TravelAgent
from travel_agent.data import load_json, load_jsonl

PERSONAS = {p["persona_id"]: p for p in load_json(config.PERSONAS_FILE)}
REQUESTS = {r["request_id"]: r for r in load_jsonl(config.TRIP_REQUESTS_FILE)}
EVENTS = {e["event_id"]: e for e in load_jsonl(config.DISRUPTIONS_FILE)}


def show(turn, agent, calls_before):
    """Print the agent's reply and what happened with the tools in this turn."""
    print(f"\nagent [{turn['status']}]>\n{turn['reply']}")
    new_calls = agent.tools.call_log[calls_before:]
    failures = Counter(c["outcome"] for c in new_calls if c["outcome"] != "ok")
    if new_calls:
        print(f"\n  (tool calls: {len(new_calls)}, failures retried: {dict(failures) or 'none'})")


def ask(prompt):
    text = input(prompt).strip()
    if text.lower() in ("q", "quit", "exit"):
        print("Bye!")
        raise SystemExit(0)
    return text


def start_conversation(agent):
    choice = ask("\nType R01-R10 for a request from the data, or press Enter to write your own: ").upper()
    if choice in REQUESTS:
        request = REQUESTS[choice]
        persona_id, text = request["persona_id"], request["text"]
        print(f"\n{PERSONAS[persona_id]['name']} ({persona_id}) writes:\n  {text}")
    else:
        for p in PERSONAS.values():
            print(f"  {p['persona_id']}: {p['name']}, from {p['home_airport']}, usually {p['usual_party']} "
                  f"traveller(s), accessibility: {p['accessibility_needs']}")
        persona_id = ask("Who is travelling? [T1/T2/T3]: ").upper()
        if persona_id not in PERSONAS:
            print("Unknown traveller.")
            return None
        text = ask("Your request: ")
    print("\n(thinking ...)")
    calls = len(agent.tools.call_log)
    turn = agent.start(persona_id, text)
    show(turn, agent, calls)
    return turn


def main():
    print("=== Travel Agent Demo ===  (type q to quit at any time)")
    agent = TravelAgent()
    turn = None
    while True:
        if turn is None or turn["status"] in ("DECLINE", "NEED_INFO", "BOOKED"):
            turn = start_conversation(agent)
            continue
        if turn["status"] == "ASK":
            answer = ask("\nyou> ")
            print("\n(thinking ...)")
            calls = len(agent.tools.call_log)
            turn = agent.answer(turn["state"], answer)
            show(turn, agent, calls)
            continue

        # a plan exists (or a booking is waiting)
        action = ask("\n[b] prepare booking   [d] disruption   [n] new request   [q] quit: ").lower()
        if action == "n":
            turn = None
        elif action == "d":
            for e in EVENTS.values():
                print(f"  {e['event_id']} (for {e['request_id']}): {e['message']}")
            event = EVENTS.get(ask("Which disruption? [D1-D5]: ").upper())
            if event is None:
                print("Unknown disruption.")
                continue
            print("\n(replanning ...)")
            calls = len(agent.tools.call_log)
            turn = agent.handle_disruption(turn["state"], event)
            show(turn, agent, calls)
        elif action == "b":
            prepared = agent.prepare_booking(turn["state"])
            print(f"\nagent [{prepared['status']}]>\n{prepared['reply']}")
            result = agent.confirm_booking(turn["state"], ask("\nyou> "))
            print(f"\nagent [{result['status']}]>\n{result['reply']}")
            if result["status"] == "BOOKED":
                turn = result


if __name__ == "__main__":
    main()
