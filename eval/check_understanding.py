"""Run the form-filling step on all trip requests and compare with eval/cases.json.

Usage: python eval/check_understanding.py   (Ollama must be running)
Writes results/understanding.json.
"""

import json
import time

from travel_agent import config
from travel_agent.data import load_json, load_jsonl
from travel_agent.understanding import complete_form, fill_form

COMPARED_FIELDS = ["destination", "party", "start_date", "end_date", "budget_total", "budget_includes",
                   "hotel_requirements", "min_activities_per_day"]


def main():
    cases = {c["request_id"]: c for c in load_json(config.EVAL_CASES_FILE)["requests"]}
    personas = {p["persona_id"]: p for p in load_json(config.PERSONAS_FILE)}
    rows = []
    for request in load_jsonl(config.TRIP_REQUESTS_FILE):
        case = cases[request["request_id"]]
        started = time.time()
        form = fill_form(request["text"])
        result = complete_form(form, personas[request["persona_id"]])
        seconds = round(time.time() - started, 1)

        should_ask = case["expected"] == "ASK"
        decision_ok = (result["decision"] == "ASK") == should_ask
        wrong_fields = []
        if "constraints" in case:
            for field in COMPARED_FIELDS:
                wanted = case["constraints"].get(field)
                got = result["constraints"].get(field)
                if field == "min_activities_per_day":
                    wanted = wanted or 0
                if field == "hotel_requirements":
                    wanted = wanted or []
                if isinstance(wanted, list):
                    wanted, got = sorted(wanted), sorted(got or [])
                if wanted is not None and wanted != got:
                    wrong_fields.append(f"{field}: got {got!r}, want {wanted!r}")
        rows.append({"request_id": request["request_id"], "expected": case["expected"], "decision": result["decision"],
                     "missing": result["missing"], "decision_ok": decision_ok, "wrong_fields": wrong_fields,
                     "seconds": seconds, "form": form, "constraints": result["constraints"],
                     "other_wishes": result["other_wishes"]})
        print(f"{request['request_id']}  expected {case['expected']:7}  got {result['decision']:4} "
              f"{'OK ' if decision_ok else 'BAD'}  missing={result['missing']}  {seconds}s")
        for w in wrong_fields:
            print(f"      field wrong -> {w}")

    decisions_ok = sum(r["decision_ok"] for r in rows)
    fields_ok = sum(not r["wrong_fields"] for r in rows)
    print(f"\nAsk/plan decision correct: {decisions_ok}/{len(rows)}")
    print(f"Requests with all checked fields correct: {fields_ok}/{len(rows)}")
    config.RESULTS_DIR.mkdir(exist_ok=True)
    out = config.RESULTS_DIR / "understanding.json"
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    print(f"Saved {out.relative_to(config.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
