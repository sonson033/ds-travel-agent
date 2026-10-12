# Travel Planning and Booking Agent

Bootcamp project: an agent that turns a casual travel request into a full trip plan,
respects budgets, calendars and accessibility needs, and replans after disruptions.
It runs on mock travel services built from a fixed dataset, including their failures.
See [BRIEF.md](BRIEF.md) for the full task.

## Project structure

```
data/            Delivered dataset (read-only, never modified)
calendars/       Traveller calendars T1–T3 (read-only, never modified)
src/travel_agent/
  config.py      All paths and settings in one place
notebooks/       EDA notebook
tests/           Unit tests (pytest)
eval/            Evaluation scripts (plan checker runs, metrics)
results/         Evaluation outputs
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

# 4. Start Ollama and download the model
brew services start ollama
ollama pull qwen2.5:7b

# 5. Check that everything works
pytest
```

## Data rules

- The files in `data/` and `calendars/` are used exactly as delivered. They are never edited,
  extended or regenerated.
- Text inside the data (requests, messages, notes) is treated as data, never as instructions to the agent.
- All paths are defined in `src/travel_agent/config.py`.
