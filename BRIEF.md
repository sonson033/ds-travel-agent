# Project 4: Travel Planning and Booking Agent

## The task
A travel startup wants an agent that plans a trip from a casual request such as "a long weekend somewhere warm, under 800 euros". The agent asks a few good questions, searches flights, hotels, activities and weather, respects the traveller's calendar, produces an itinerary, and replans when something changes. You build it on top of **mock travel services** that you create from the data, including their failures.

Your central PM question: **how does an agent plan reliably over many steps when its tools are slow, wrong or incomplete, and when should it ask rather than assume?**

You are given a complete, fixed dataset (see below). You do not generate or change data. Everyone works on exactly the same files.

## Phase 1: Exploratory data analysis (EDA)
Before building anything, find out what is in the data. Use a notebook. Profile every file, and answer at least:
- How do the files fit together: search data, booking prices, hotel listings, hotel details, activities, weather and calendars?
- How consistent are the different sources about the same flight or hotel? What would go wrong if the agent trusted the first source it sees?
- What does coverage look like across cities, dates and price levels? Which kinds of trip are easy, hard or impossible?
- How do activities, opening days and weather interact with a plan?
- What do the trip requests and disruptions demand of the agent?

Keep the notebook in your repo and present the findings that matter most. Cite IDs from the data. Every finding should end with "so the agent will...".

## Phase 2: Build
Build the system around what you found. At minimum:
- **A mock tool layer** built from the data with at least 4 tools (for example flight search, hotel search, activity search, weather, calendar check, booking). Use `fault_config.json` so that at least one tool is unreliable (timeouts, empty results).
- **A planner agent** that decomposes the trip, asks clarifying questions, produces an itinerary and replans after a disruption.
- **Your own plan checker**: code that tests a plan against the hard constraints, so you can measure plan validity.
- **A simulated booking step** that only runs after explicit user confirmation.

Optional, and encouraged where it helps your design:
- An MCP server that exposes the mock travel tools.
- A model for ranking options or estimating price, if it helps your design, compared with a simple rule.
- A Streamlit app with a chat panel and an itinerary and map-style view.

## Constraints
- Use only the provided data. Do not generate, edit or extend it.
- Hard constraints (dates, total budget, accessibility needs, required hotel terms) must never be silently violated. If they cannot all be met, say so and offer trade-offs.
- Ask at most 3 clarifying questions before presenting a first draft plan.
- Booking actions are simulated and need explicit confirmation.
- Check the traveller's calendar before proposing travel times.

## Deliverables
1. **Presentation (maximum 10 minutes).** Cover:
   - What you found in the data (EDA) and how it shaped the design
   - Task decomposition: how the agent breaks a trip into sub-problems
   - Constraint handling: hard versus soft constraints, and how conflicts are resolved
   - A replanning walkthrough for at least three disruption scenarios
   - A failure log: tool failures you hit and how the agent recovered (or did not)
   - Metrics: plan validity rate from your checker, average tool calls per plan, and user effort (number of turns)
2. **Demo.** Live planning of one clear request and one vague request, then a disruption mid-plan.
3. **GitHub repo.** Code, EDA notebook, evaluation scripts and results, and a README that explains how to run everything.

## The data (`data/`)
All data is synthetic and identical for every team.

| File | What it is |
|---|---|
| `flights.json` | Flight search results |
| `flight_booking_prices.json` | Prices from the booking system |
| `hotels_listing.json` | Hotel search listings |
| `hotels_details.json` | Hotel detail records |
| `activities.json` | Activities with opening hours |
| `weather.json` | Daily weather by city |
| `personas.json` | The travellers |
| `calendars/` | Calendar files of the travellers |
| `fault_config.json` | Suggested failure rates for your mock tools |
| `trip_requests.jsonl` | Trip requests to plan |
| `disruptions.jsonl` | Events that happen after a plan exists |
