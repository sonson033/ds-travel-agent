"""Read-only loaders for the delivered data, shared by the tools and the plan checker."""

import json

from icalendar import Calendar

from travel_agent import config


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_jsonl(path):
    """One JSON object per line (trip requests, disruptions)."""
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_calendar(persona_id):
    """Events of one traveller as dicts with naive datetimes: start, end, summary."""
    cal = Calendar.from_ical(config.calendar_file(persona_id).read_bytes())
    return [
        {"start": ev.decoded("DTSTART"), "end": ev.decoded("DTEND"), "summary": str(ev.get("SUMMARY"))}
        for ev in cal.walk("VEVENT")
    ]
