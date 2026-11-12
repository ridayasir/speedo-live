# Route data

## What ships with the app

The three routes in `backend/seed/demo_network.json` (**DEMO-1, DEMO-2, DEMO-3**), their buses (**DEMO-101 … DEMO-302**), stops and timetables are **sample data I created for demonstration**. They are not official Speedo routes, bus numbers or schedules:

- stop names are well-known Lahore landmarks, with approximate coordinates
- route lines are straight segments between stops, not the roads buses actually use
- timetables (first/last departure, frequency) are invented

Every one of them is flagged `is_demo` / `verified = false`, and passengers see a DEMO badge and banner. They are only seeded when `SPEEDO_MODE=demo`.

## Loading real Speedo routes

Get route lists, stop locations and timetables from the **Punjab Mass Transit Authority (PMA)**, **Punjab Transport Company**, or other official publications. Don't copy unofficial lists into the app as if they were verified.

1. Admin → Routes → **Import CSV / Excel** → *Download template*.
2. One row per stop:

| Column | Required | Example |
|---|---|---|
| `route_code` | yes | as printed by the operator |
| `route_name` | yes | |
| `route_color` | no | `#1D4ED8` |
| `stop_seq` | yes | 1, 2, 3 … in travel order (outbound) |
| `stop_code` | yes | unique per stop; a stop shared by routes uses the same code |
| `stop_name`, `stop_name_ur` | name yes, Urdu optional | |
| `lat`, `lon` | yes | WGS84 decimal degrees; must fall inside the Lahore service area |
| `days`, `first_departure`, `last_departure`, `headway_min` | optional (first row of the route) | `MON,TUE,…`, `06:30`, `22:00`, `10` |

3. Enter the **source** (e.g. "PMA feeder routes notice, Nov 2026"), click **Check file** (dry run shows errors and what will change), then **Import**. Tick *verified* only when the data comes from the official source.
4. Re-importing a route with the same code replaces its stops and timetable, which is how you apply changes when the authority revises a service.
5. For accurate ETAs, paste the road geometry (`[[lat, lon], …]` following the streets) into Admin → Routes → *Road geometry*. Without it, distances are straight lines between stops and ETAs are rougher.
