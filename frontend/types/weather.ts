// Mirrors the Weather Agent models in backend/app/schemas/weather.py
import type { DataMeta, WeatherEvent } from "@/types/api";
import type { ParsedQuery } from "@/types/query";

export type WeatherStatus =
  | "matched" | "partial_match" | "no_match" | "no_active_events" | "unsupported_event";

export interface WeatherRequest {
  event_type: "hurricane" | "tropical_storm" | "none";
  event_category: number | null;
  region: string | null;
  sectors: string[];
  time_horizon: string | null;
  time_horizon_days: number | null;
}

export interface EventMatch {
  event: WeatherEvent;
  match: "full" | "partial" | "none";
  type_match: boolean;
  region_match: boolean;
  category_match: boolean | null; // null = no category was requested
}

export interface WeatherIntelligence {
  meta: DataMeta | null; // null only when no provider was queried (unsupported event)
  status: WeatherStatus;
  request: WeatherRequest;
  events: EventMatch[];
  primary_event: WeatherEvent | null;
  affected_regions: string[];
  affected_infrastructure: string[];
  affected_sectors: string[];
  relevant_sectors: string[];
  severity: "LOW" | "MODERATE" | "HIGH" | "EXTREME" | null;
  forecast_available: boolean;
  summary: string;
  warnings: string[];
}

export interface WeatherAgentResponse {
  query: string | null;
  parsed: ParsedQuery;
  parse_notice: string | null;
  weather: WeatherIntelligence;
}

// UI state of the weather step shown under a parsed question.
export type WeatherSlot =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; data: WeatherIntelligence }
  | { kind: "error"; message: string };
