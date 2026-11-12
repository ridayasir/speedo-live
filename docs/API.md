# Speedo Live API reference

Interactive docs: run the server and open **/docs** (Swagger UI). Machine-readable spec: [`openapi.json`](openapi.json) (also served at `/openapi.json`).

Auth: send `Authorization: Bearer <token>` from `POST /api/auth/login`. Errors are always `{"error": {"code", "message", "details?"}}`.

Real-time: `GET /api/live/stream` (Server-Sent Events: `snapshot`, `bus`, `alert`, `ping`) or WebSocket `/ws/live` with the same filters (`route_id`, `bus_id`; admins add a `ticket` from `POST /api/admin/stream-ticket`).

## Auth

| Method | Path | Access | What it does |
|---|---|---|---|
| POST | `/api/auth/register` | public | Create a passenger account (email or Pakistani mobile number). |
| POST | `/api/auth/login` | public | Sign in with email or phone number and password. Returns a JWT. |
| POST | `/api/auth/logout` | passenger, driver, admin | Revoke the current token. A driver's active trip is closed as interrupted. |

## Account

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/me` | passenger, driver, admin | Current user profile. |
| PATCH | `/api/me` | passenger, driver, admin | Update name/phone or change password. |
| GET | `/api/me/favorites` | passenger, driver, admin | Favourite routes and stops. |
| POST | `/api/me/favorites/routes` | passenger, driver, admin | Add a favourite route |
| DELETE | `/api/me/favorites/routes/{id}` | passenger, driver, admin | Remove a favourite route |
| POST | `/api/me/favorites/stops` | passenger, driver, admin | Add a favourite stop |
| DELETE | `/api/me/favorites/stops/{id}` | passenger, driver, admin | Remove a favourite stop |
| GET | `/api/me/history` | passenger, driver, admin | Journey history (most recent first). |
| POST | `/api/me/history` | passenger, driver, admin | Record a journey the user started. |
| DELETE | `/api/me/history` | passenger, driver, admin | Delete all journey history. |

## Public

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/config` | public | App mode and tracking settings for clients. |
| GET | `/api/alerts` | public | Active service alerts. |

## Routes

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/routes` | public | All routes with summary info. |
| GET | `/api/routes/{id}` | public | Route geometry, ordered stops and live buses. |

## Stops

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/stops` | public | Search stops by text and/or proximity (nearest first when lat/lon given). |
| GET | `/api/stops/{id}` | public | Stop info, routes serving it and alerts. |

## Live

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/buses` | public | Current bus positions and status (active, delayed, stale, offline, out_of_service). |
| GET | `/api/buses/{id}` | public | One bus with its route, next stops and ETAs to the remaining stops. |
| GET | `/api/live/stream` | public | Server-Sent Events stream of bus updates. Events: `snapshot` (all matching buses), `bus` (one bus changed), `ping`. |

## Eta

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/stops/{id}/arrivals` | public | Live ETAs of approaching buses, plus timetable estimates (labelled 'scheduled'). |

## Journeys

| Method | Path | Access | What it does |
|---|---|---|---|
| POST | `/api/journeys/plan` | public | Find Speedo routes between two places (with up to one transfer). |

## Timetable

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/timetable` | public | Route timetable for a date (default today, Asia/Karachi). |

## Notifications

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/me/notification-preferences` | passenger, driver, admin | Notification preferences. |
| PUT | `/api/me/notification-preferences` | passenger, driver, admin | Update notification preferences. |
| GET | `/api/me/notifications` | passenger, driver, admin | In-app notification inbox. |
| POST | `/api/me/notifications/read` | passenger, driver, admin | Mark all notifications as read. |
| POST | `/api/me/devices` | passenger, driver, admin | Register an FCM device token for push notifications. |
| GET | `/api/me/watches` | passenger, driver, admin | Active 'notify me when the bus approaches' requests. |
| POST | `/api/me/watches` | passenger, driver, admin | Ask to be notified when a bus on a route approaches a stop. |
| DELETE | `/api/me/watches/{id}` | passenger, driver, admin | Cancel a watch. |

## Driver

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/driver/me` | driver | Driver profile, assigned bus and route, current trip. |
| POST | `/api/driver/consent` | driver | Record (or withdraw) consent to share location while on a trip. |
| POST | `/api/driver/trips/start` | driver | Start a trip on the assigned bus. Resumes the existing trip after an app restart. |
| POST | `/api/driver/trips/end` | driver | End the current trip; location sharing stops. |
| POST | `/api/driver/location` | driver | Send one GPS fix (every ~5–10 s while a trip is active). |
| POST | `/api/driver/location/batch` | driver | Flush fixes queued while offline (max 100, any order; duplicates are ignored). |
| GET | `/api/driver/trips` | driver | The driver's recent trips. |

## Admin

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/api/admin/overview` | admin | Dashboard counters. |
| POST | `/api/admin/stream-ticket` | admin | Short-lived ticket for the admin live stream (EventSource can't send headers). |
| GET | `/api/admin/fleet` | admin | All buses with driver, GPS and trip details. |
| GET | `/api/admin/buses` | admin | List buses. |
| POST | `/api/admin/buses` | admin | Add a bus. |
| PATCH | `/api/admin/buses/{id}` | admin | Edit a bus, assign route/driver, or change status. |
| DELETE | `/api/admin/buses/{id}` | admin | Delete a bus (blocked while it has an active trip; deactivate it instead). |
| POST | `/api/admin/trips/{id}/end` | admin | Force-end a trip (e.g. a driver forgot to end it). |
| GET | `/api/admin/stops` | admin | List stops with the routes serving them. |
| POST | `/api/admin/stops` | admin | Add a stop. |
| PUT | `/api/admin/stops/{id}` | admin | Edit a stop (routes using it are re-measured). |
| DELETE | `/api/admin/stops/{id}` | admin | Delete a stop that no route uses. |
| GET | `/api/admin/routes` | admin | All routes (including inactive) with stops. |
| POST | `/api/admin/routes` | admin | Create a route with ordered stops (first = start, last = end) and optional geometry. |
| PATCH | `/api/admin/routes/{id}` | admin | Edit a route: details, status, stop order or geometry. |
| DELETE | `/api/admin/routes/{id}` | admin | Delete a route (buses on it become unassigned). Blocked while trips are active. |
| GET | `/api/admin/drivers` | admin | List drivers with assigned bus and current trip state. |
| POST | `/api/admin/drivers` | admin | Create a driver account (and optionally assign a bus). |
| PATCH | `/api/admin/drivers/{id}` | admin | Edit a driver, (de)activate the account, assign/unassign a bus, reset password. |
| GET | `/api/admin/schedules` | admin | All timetable entries. |
| POST | `/api/admin/schedules` | admin | Add a timetable entry (service days, first/last departure, headway). |
| PUT | `/api/admin/schedules/{id}` | admin | Replace a timetable entry. |
| DELETE | `/api/admin/schedules/{id}` | admin | Delete a timetable entry. |
| GET | `/api/admin/alerts` | admin | All service alerts. |
| POST | `/api/admin/alerts` | admin | Publish a service alert; followers of the route/stop are notified. |
| PATCH | `/api/admin/alerts/{id}` | admin | End or edit an alert. |
| GET | `/api/admin/reports/daily` | admin | Daily operations report (trips, bus activity, route usage, GPS availability, delays, interruptions). format=csv exports trips. |
| GET | `/api/admin/import/template.csv` | admin | CSV template for importing verified route data. |
| POST | `/api/admin/import` | admin | Upload a CSV/XLSX of routes and stops (multipart field `file`). Use dry_run=true to validate first. |
| GET | `/api/admin/settings` | admin | Effective configuration and integration status (read-only; set via environment variables). |
