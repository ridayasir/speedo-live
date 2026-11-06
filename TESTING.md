# Speedo Live testing report

Date: 5 November 2026. Environment: Linux cloud workspace, Python 3.13, PostgreSQL 16 + PostGIS 3.4, Redis 7, Node 22, Chromium (Playwright).

## Summary

| Area | How it was tested | Result |
|---|---|---|
| Backend API, database, GPS, ETA | 34 automated tests (pytest) against a real PostGIS database | **34 passed** |
| Real-time WebSocket feed | Automated test (driver GPS → WebSocket message) and a manual client against the running server | Pass |
| Passenger web app | Headless Chromium: every page loaded, journey search, bus selection, sign-in, no console errors | Pass |
| Admin dashboard | Headless Chromium: sign-in and all 10 sections load with data, no console errors | Pass |
| Mobile browser layout | Pixel 7 emulation: no horizontal overflow, bottom navigation shown | Pass |
| Docker image (API + website) | Built and run with Docker Compose (PostGIS + Redis); health check, live buses, full browser run | Pass |
| Passenger Android app | TypeScript check and full Android JavaScript bundle (`expo export -p android`) | Compiles; **not run on a device** |
| Driver Android app | TypeScript check and full Android JavaScript bundle | Compiles; **not run on a device** |
| Cloud deployment | Not done: needs a hosting account | **Not tested** |
| Push notifications to a phone | Needs Firebase project; notification creation, preferences and de-duplication are tested | **Delivery not tested** |

## Automated test coverage (backend/tests)

| Requirement | Test(s) |
|---|---|
| Passenger registration | `test_register_login_logout`, `test_register_requires_contact_and_password_rules` |
| Login and logout | `test_register_login_logout`, `test_wrong_password`, `test_password_is_hashed` |
| Route search, stop search | `test_route_and_stop_search` |
| Journey planning (direct and one transfer) | `test_journey_planning_direct_and_transfer`, `test_plan_validation` |
| Timetable filters | `test_timetable_filters` |
| Bus selection, live map sync | `test_trip_gps_flow_and_live_sync` (WebSocket receives the driver's update) |
| GPS updates | `test_trip_gps_flow_and_live_sync` (batch of 6 fixes accepted, progress along route) |
| Duplicate GPS updates | `test_trip_gps_flow_and_live_sync` (resent fixes counted as duplicates) |
| Invalid GPS coordinates | `test_invalid_coordinates_rejected` (4 cases), rejected batch in `test_trip_gps_flow_and_live_sync` |
| Low accuracy / bad timestamps | `test_low_accuracy_and_future_timestamps_rejected` |
| ETA calculation | `test_eta_uses_distance_and_speed`, live arrival in `test_trip_gps_flow_and_live_sync` |
| Stale location detection | `test_stale_and_offline_detection`, `test_stale_is_not_reported_as_stopped` |
| Offline GPS handling / interrupted trips | `test_offline_trip_gets_interrupted` |
| Driver authentication and consent | `test_driver_requires_consent_and_role` |
| Driver limited to assigned bus | `test_driver_cannot_report_other_bus` |
| Trip start and end | `test_trip_gps_flow_and_live_sync` (start, resume, end, GPS refused after end) |
| Admin permissions | `test_admin_permissions` (passenger, driver and anonymous all refused) |
| Admin CRUD, stop reordering, driver deactivation | `test_admin_overview_and_crud` |
| Schedule management | `test_admin_overview_and_crud` (create, invalid times refused, update) |
| Notification delivery logic | `test_arrival_watch_notifies`, `test_favorites_prefs_and_disruption_notification`, `test_notification_prefs_block_kind` |
| Privacy of driver data | `test_public_bus_data_hides_driver_details` |
| CSV route import | `test_csv_import` |
| Reports | `test_reports` |
| DEMO simulator only moves demo buses | `test_simulator_moves_demo_buses_only` |
| API documentation | `test_openapi_docs` |

Run: `cd backend && pytest -q`

## Known gaps and next tests

1. **Android apps on a real phone.** Install the preview APKs and check: map loads, live buses move, journey
   planning, notifications; for the driver app, start a trip, lock the screen for 10 minutes, switch to airplane
   mode and back (queued fixes should arrive), end the trip.
2. **Driver testing outside Lahore.** The server rejects GPS outside the Lahore service area. To test elsewhere,
   temporarily widen `AREA_MIN_LAT` etc. on a test server.
3. **Load.** Not load-tested. A single instance handles the demo fleet easily; for hundreds of buses run 2+
   instances with Redis and check database write volume.
4. **Route geometry.** Demo lines are straight between stops. Real routes should be imported with a shapes file.
