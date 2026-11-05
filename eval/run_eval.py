"""Run the whole agent (real language model, real tool failures) on all trip requests and disruptions.

Usage: python eval/run_eval.py   (Ollama must be running, takes a few minutes)
Writes results/eval_results.json and results/eval_summary.md.
"""

import json
import time
from collections import Counter

from travel_agent import config
from travel_agent.agent import TravelAgent
from travel_agent.checker import PlanChecker
from travel_agent.data import load_json, load_jsonl
from travel_agent.tools import TravelTools

# Agent status -> reaction category. NEED_INFO means it kept asking.
REACTION = {"PLAN": "PLAN", "DECLINE": "DECLINE", "ASK": "ASK", "NEED_INFO": "ASK"}


def reaction_ok(expected, reaction, is_disruption):
    if expected == reaction:
        return True
    # After a disruption, "ASK" means: do not silently plan, let the traveller decide.
    # A DECLINE with options (other dates, higher budget) does exactly that.
    return is_disruption and expected == "ASK" and reaction == "DECLINE"


def run_case(case_id, persona_id, text, expected, gold, event=None):
    tools = TravelTools()  # seed and failure rates from fault_config.json, fresh for every case
    agent = TravelAgent(tools=tools)
    started = time.time()
    turn = agent.start(persona_id, text)
    if event is not None:
        base_plan = turn.get("plan")
        if not base_plan:
            raise RuntimeError(f"{case_id}: no base plan to disrupt")
        gold = dict(gold)  # the cancelled flight / sold-out hotel depends on the base plan
        if event["event_type"] == "flight_cancelled":
            gold["excluded_flights"] = [base_plan["flights"]["outbound"]]
        if event["event_type"] == "hotel_sold_out":
            gold["excluded_hotels"] = [base_plan["hotel"]["hotel_id"]]
        turn = agent.handle_disruption(turn["state"], event)

    reaction = REACTION[turn["status"]]
    check = PlanChecker().check(turn["plan"], gold) if reaction == "PLAN" and gold else None
    outcomes = Counter(c["outcome"] for c in tools.call_log)
    return {
        "case": case_id, "expected": expected, "reaction": reaction,
        "reaction_ok": reaction_ok(expected, reaction, event is not None),
        "plan_valid": check["valid"] if check else None,
        "violations": check["violations"] if check else [],
        "total_price": turn.get("total_price"), "tool_calls": len(tools.call_log),
        "tool_failures": {k: v for k, v in outcomes.items() if k != "ok"},
        "unrecovered_failures": turn.get("failures", []),
        "turns": turn["state"]["turns"], "seconds": round(time.time() - started, 1),
        "reply": turn["reply"],
    }


def main():
    cases = load_json(config.EVAL_CASES_FILE)
    requests = {r["request_id"]: r for r in load_jsonl(config.TRIP_REQUESTS_FILE)}
    events = {e["event_id"]: e for e in load_jsonl(config.DISRUPTIONS_FILE)}
    gold = {c["request_id"]: c.get("constraints", {}) for c in cases["requests"]}

    rows = []
    for c in cases["requests"]:
        r = requests[c["request_id"]]
        rows.append(run_case(c["request_id"], r["persona_id"], r["text"], c["expected"], gold[c["request_id"]]))
        print_row(rows[-1])
    for c in cases["disruptions"]:
        r, event = requests[c["request_id"]], events[c["event_id"]]
        changed_gold = {**gold[c["request_id"]], **c["constraint_changes"]}
        rows.append(run_case(c["event_id"], r["persona_id"], r["text"], c["expected"], changed_gold, event))
        print_row(rows[-1])

    summary = summarize(rows)
    print("\n" + "\n".join(f"{k}: {v}" for k, v in summary.items()))
    config.RESULTS_DIR.mkdir(exist_ok=True)
    (config.RESULTS_DIR / "eval_results.json").write_text(
        json.dumps({"summary": summary, "cases": rows}, indent=2, ensure_ascii=False))
    (config.RESULTS_DIR / "eval_summary.md").write_text(markdown(rows, summary))
    print("Saved results/eval_results.json and results/eval_summary.md")


def print_row(row):
    valid = {True: "valid", False: "INVALID", None: "-"}[row["plan_valid"]]
    print(f"{row['case']:4} expected {row['expected']:7} got {row['reaction']:7} "
          f"{'OK ' if row['reaction_ok'] else 'BAD'} plan {valid:7} calls {row['tool_calls']:3} "
          f"turns {row['turns']} failures {row['tool_failures']} {row['seconds']}s")
    for v in row["violations"]:
        print(f"      violation -> {v['rule']}: {v['message']}")


def summarize(rows):
    plans = [r for r in rows if r["plan_valid"] is not None]
    planned = [r for r in rows if r["reaction"] == "PLAN"]
    failures = Counter()
    for r in rows:
        failures.update(r["tool_failures"])
    return {
        "correct reaction": f"{sum(r['reaction_ok'] for r in rows)}/{len(rows)}",
        "plan validity rate": f"{sum(r['plan_valid'] for r in plans)}/{len(plans)} plans valid",
        "avg tool calls per plan": round(sum(r["tool_calls"] for r in planned) / len(planned), 1) if planned else None,
        "avg turns (user effort)": round(sum(r["turns"] for r in rows) / len(rows), 2),
        "tool failures (all cases)": dict(failures),
        "cases with unrecovered failures": [r["case"] for r in rows if r["unrecovered_failures"]],
        "avg seconds per case": round(sum(r["seconds"] for r in rows) / len(rows), 1),
    }


def markdown(rows, summary):
    lines = ["| Case | Expected | Agent | Correct | Plan valid | Price | Tool calls | Turns | Tool failures |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        valid = {True: "yes", False: "NO", None: "-"}[r["plan_valid"]]
        price = f"{r['total_price']:.0f} EUR" if r["total_price"] is not None else "-"
        lines.append(f"| {r['case']} | {r['expected']} | {r['reaction']} | {'yes' if r['reaction_ok'] else 'NO'} | "
                     f"{valid} | {price} | {r['tool_calls']} | {r['turns']} | {r['tool_failures'] or '-'} |")
    lines += ["", *(f"- **{k}:** {v}" for k, v in summary.items())]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
