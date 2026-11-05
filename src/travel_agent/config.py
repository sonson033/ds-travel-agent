"""Central project configuration. All paths are defined here and nowhere else.

The folders data/ and calendars/ are read-only inputs: never write to them.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = two levels above this file (src/travel_agent/config.py -> repo root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Read-only input data (as delivered, never modified)
DATA_DIR = PROJECT_ROOT / "data"
CALENDAR_DIR = PROJECT_ROOT / "calendars"

# Our own outputs
RESULTS_DIR = PROJECT_ROOT / "results"
EVAL_DIR = PROJECT_ROOT / "eval"
NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"
EVAL_CASES_FILE = EVAL_DIR / "cases.json"  # expected behaviour per request/disruption

# Individual data files
FLIGHTS_FILE = DATA_DIR / "flights.json"
FLIGHT_BOOKING_PRICES_FILE = DATA_DIR / "flight_booking_prices.json"
HOTELS_LISTING_FILE = DATA_DIR / "hotels_listing.json"
HOTELS_DETAILS_FILE = DATA_DIR / "hotels_details.json"
ACTIVITIES_FILE = DATA_DIR / "activities.json"
WEATHER_FILE = DATA_DIR / "weather.json"
PERSONAS_FILE = DATA_DIR / "personas.json"
FAULT_CONFIG_FILE = DATA_DIR / "fault_config.json"
TRIP_REQUESTS_FILE = DATA_DIR / "trip_requests.jsonl"
DISRUPTIONS_FILE = DATA_DIR / "disruptions.jsonl"

DATA_FILES = [
    FLIGHTS_FILE,
    FLIGHT_BOOKING_PRICES_FILE,
    HOTELS_LISTING_FILE,
    HOTELS_DETAILS_FILE,
    ACTIVITIES_FILE,
    WEATHER_FILE,
    PERSONAS_FILE,
    FAULT_CONFIG_FILE,
    TRIP_REQUESTS_FILE,
    DISRUPTIONS_FILE,
]


def calendar_file(persona_id: str) -> Path:
    """Path to a traveller's calendar, e.g. calendar_file("T1") -> calendars/T1.ics."""
    return CALENDAR_DIR / f"{persona_id}.ics"


# LLM settings (local Ollama), overridable via .env
load_dotenv(PROJECT_ROOT / ".env")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
