export type Role = "passenger" | "driver" | "admin";

export interface User {
  id: number;
  full_name: string;
  email: string | null;
  phone: string | null;
  role: Role;
  is_active: boolean;
  notification_prefs: NotificationPrefs;
  created_at: string;
}

export interface NotificationPrefs {
  bus_approaching: boolean;
  arrival_minutes_before: number;
  delays: boolean;
  disruptions: boolean;
  schedule_changes: boolean;
}

export interface Stop {
  id: number;
  code: string;
  name: string;
  name_ur?: string | null;
  lat: number;
  lng: number;
  is_demo: boolean;
  distance_m?: number;
  source_reference?: string | null;
}

export interface RouteStopDetail extends Stop {
  sequence: number;
  distance_m: number;
  offset_minutes: number;
  is_major: boolean;
}

export interface Schedule {
  id: number;
  route_id: number;
  route_code?: string;
  days: string[];
  first_departure: string;
  last_departure: string;
  frequency_minutes: number;
  notes: string | null;
  is_demo: boolean;
}

export interface RouteSummary {
  id: number;
  code: string;
  name: string;
  color: string;
  status: string;
  start_stop: Stop | null;
  end_stop: Stop | null;
  length_m: number;
  stop_count: number;
  fare_pkr: number | null;
  avg_speed_kmh: number | null;
  is_demo: boolean;
  source_reference: string | null;
}

export interface RouteDetail extends RouteSummary {
  path: [number, number][];
  stops: RouteStopDetail[];
  schedules: Schedule[];
  alerts?: Alert[];
}

export type BusStatus = "active" | "delayed" | "stale" | "offline" | "idle" | "out_of_service";

export interface BusState {
  bus_id: number;
  bus_number: string;
  route_id: number | null;
  trip_id: number | null;
  lat: number | null;
  lng: number | null;
  heading: number | null;
  speed_kmh: number | null;
  accuracy_m: number | null;
  last_gps_at: string | null;
  gps_age_seconds: number | null;
  gps: "fresh" | "stale" | "offline" | "none";
  status: BusStatus;
  motion: "moving" | "stopped" | null;
  next_stop: { id: number; name: string; distance_m: number } | null;
  progress_m: number | null;
  delay_minutes: number | null;
  is_demo: boolean;
  source: string | null;
}

export interface LiveArrival {
  kind: "live";
  route_id: number;
  route_code: string;
  route_name: string;
  bus_id: number;
  bus_number: string;
  trip_id: number;
  eta: string;
  minutes: number;
  distance_m: number;
  bus_lat: number;
  bus_lng: number;
  last_gps_at: string;
  is_demo: boolean;
}

export interface ScheduledArrival {
  kind: "scheduled";
  route_id: number;
  route_code: string;
  route_name: string;
  eta: string;
  minutes: number;
  is_demo: boolean;
}

export interface Arrivals {
  stop_id: number;
  generated_at: string;
  live: LiveArrival[];
  scheduled: ScheduledArrival[];
}

export interface Alert {
  id: number;
  route_id: number | null;
  stop_id: number | null;
  severity: "info" | "warning" | "disruption";
  title: string;
  message: string;
  starts_at: string | null;
  ends_at: string | null;
  is_active: boolean;
  created_at: string;
}

export interface PlanLegRide {
  type: "ride";
  route_id: number;
  route_code: string;
  route_name: string;
  color: string;
  board: Stop;
  alight: Stop;
  stops: Stop[];
  stop_count: number;
  distance_m: number;
  minutes: number;
  is_demo: boolean;
}

export interface PlanLegWalk {
  type: "walk";
  from: { lat: number; lng: number; name?: string };
  to: { lat: number; lng: number; name?: string };
  distance_m: number;
  minutes: number;
}

export type PlanLeg = PlanLegRide | PlanLegWalk;

export interface PlanOption {
  legs: PlanLeg[];
  total_minutes: number;
  wait_minutes: number;
  transfers: number;
  walk_m: number;
  is_demo: boolean;
}

export interface PlanResult {
  origin: { lat: number; lng: number; name: string };
  destination: { lat: number; lng: number; name: string };
  nearest_boarding_stop: (Stop & { walk_m: number }) | null;
  nearest_destination_stop: (Stop & { walk_m: number }) | null;
  options: PlanOption[];
  straight_line_m: number;
}

export interface Meta {
  app: string;
  tagline: string;
  data_source: string;
  demo_mode: boolean;
  notice: string;
  stale_after_seconds: number;
  map_center: [number, number];
}
