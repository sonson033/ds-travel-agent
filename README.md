# Travel Planning and Booking Agent

Bootcamp project: an agent that turns a casual travel request into a full trip plan,
respects budgets, calendars and accessibility needs, and replans after disruptions.
It runs on mock travel services built from a fixed dataset, including their failures.
See [BRIEF.md](BRIEF.md) for the full task.

**Core question:** how does an agent plan reliably when its tools are slow, wrong or incomplete,
and when should it ask rather than assume?

**Our answer in one sentence:** the language model only handles language (reading the request,
writing a short comment); fixed rules in code decide when to ask, plan with the unreliable tools,
check the plan and book only after an explicit "yes".

## Results

All 10 trip requests and 5 disruptions, real language model (`qwen2.5:7b` via Ollama),
real tool failure rates from `data/fault_config.json`:

| Metric | Result |
|---|---|
| Correct reaction (plan / ask / decline) | 15/15 |
| Plan validity rate (own plan checker) | 7/7 plans valid |
| Avg tool calls per plan | 41 (incl. replanning after disruptions; 27–31 without) |
| User effort | 1.33 turns on average |
| Tool failures | 64 timeouts, all recovered by retries |

Details per case: [results/eval_summary.md](results/eval_summary.md).
Limitation: in this run only timeouts occurred; empty results and failed bookings are covered by unit tests.

## How it works

```
trip request (free text)
  │
  ├─ 1. understanding.py   language model fills in a fixed form (destination, dates, party, budget, ...)
  ├─ 2. complete_form      fixed rules: fill gaps from the persona, ASK if dates/destination/budget are missing
  ├─ 3. planner.py         code only, mock tools only: calendar → flights + booking prices → hotels + details
  │                        (requirements must hold in BOTH hotel sources) → activities → cheapest valid plan
  │                        or DECLINE with reasons; timeouts/empty results are retried up to 3 times
  ├─ 4. agent.py           plan details written by code; the model adds a 1–3 sentence comment
  │                        (warnings, weather vs. wishes); declines offer a fixed list of options
  └─ 5. booking            prepare_booking (exact prices) → traveller types "yes" → confirm_booking (code only)

disruption (D1–D5) → one fixed rule per event type (exclude flight/hotel, cut budget, block outdoor day,
add traveller) → plan again
```

The plan checker (`checker.py`) is the referee: it reads the data directly (no tool failures)
and tests a plan against the hard constraints. The planner never uses it, so the evaluation stays honest.

## Project structure

```
data/                 Delivered dataset (read-only, never modified)
calendars/            Traveller calendars T1–T3 (read-only, never modified)
src/travel_agent/
  config.py           All paths and settings in one place
  data.py             Read-only loaders (JSON, JSONL, calendars)
  tools.py            Mock travel tools with failures from fault_config.json (seeded)
  checker.py          Plan checker: hard constraints (violations) and soft warnings
  understanding.py    Language model fills in the request form; fixed rules decide ASK or PLAN
  planner.py          Builds the cheapest valid plan using only the mock tools
  agent.py            Conversation: questions, plan, decline, disruptions, booking
notebooks/
  01_eda.ipynb        Exploratory data analysis ("so the agent will ..." findings)
tests/                Unit tests (pytest, no language model needed)
eval/
  cases.json          Expected behaviour per request/disruption (PLAN / ASK / DECLINE)
  check_understanding.py   Evaluates the form-filling step on all 10 requests
  run_eval.py         Evaluates the whole agent on all 15 cases
results/              Evaluation outputs
demo.py               Interactive terminal demo
```

## Setup (macOS)

Requirements: [Homebrew](https://brew.sh).

```bash
# 1. Install Python 3.12 and Ollama
brew install python@3.12 ollama

# 2. Create the virtual environment and install dependencies
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Optional: local settings (defaults work without this)
cp .env.example .env

# 4. Start Ollama and download the model (about 4.7 GB)
brew services start ollama
ollama pull qwen2.5:7b

# 5. Check that everything works
pytest
```

## How to run

All commands from the project folder with the virtual environment active (`source .venv/bin/activate`).

```bash
# Interactive terminal demo (Ollama must be running)
python demo.py
#   R01-R10 = use a request from the data, or press Enter to type your own
#   after a plan: b = prepare booking (then type yes), d = disruption D1-D5, n = new request, q = quit

# Unit tests (fast, no language model)
pytest

# EDA notebook: open notebooks/01_eda.ipynb in VS Code (kernel: .venv) and run all cells

# Evaluation with the real language model (Ollama must be running)
python eval/check_understanding.py   # form filling on all 10 requests -> results/understanding.json
python eval/run_eval.py              # whole agent on all 15 cases   -> results/eval_results.json, eval_summary.md
```

Using the agent from Python:

```python
from travel_agent.agent import TravelAgent

agent = TravelAgent()
turn = agent.start("T1", "A long weekend somewhere warm, under 800 euros.")
print(turn["reply"])                       # asks for the dates
turn = agent.answer(turn["state"], "13 to 16 November")
print(turn["reply"])                       # plan with prices
prepared = agent.prepare_booking(turn["state"])
print(prepared["reply"])                   # exact price, nothing booked yet
print(agent.confirm_booking(turn["state"], "yes")["reply"])   # books only on "yes" / "ja"
```

## Data rules

- The files in `data/` and `calendars/` are used exactly as delivered. They are never edited,
  extended or regenerated.
- Text inside the data (requests, messages, notes) is treated as data, never as instructions to the agent.
  Example: disruption D1 says "Please rebook" – the agent replans but books nothing without an explicit "yes".
- All paths are defined in `src/travel_agent/config.py`.

## Assumptions (not stated in the data)

- Flight and activity prices are per person, hotel prices per room and night, one room per party.
- Activities are planned only on full days between arrival and departure day.
- "Free cancellation" means `free_cancellation` only, not `free_until_48h`.
- When hotel listing and details disagree, a requirement only counts if both sources confirm it,
  and the higher price is used.
