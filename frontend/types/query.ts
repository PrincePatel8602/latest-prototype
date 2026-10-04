// Mirrors backend/app/schemas/query.py
export type Intent =
  | "event_impact" | "portfolio_risk" | "historical_search"
  | "exposure" | "explain_risk" | "hedging" | "other";

export type AnalysisStep =
  | "weather" | "news" | "market" | "historical" | "exposure" | "scenario" | "risk" | "drivers" | "fusion" | "hedging";

export interface ParsedQuery {
  intent: Intent;
  event_type: string;
  event_category: number | null;
  region: string | null;
  sectors: string[];
  assets: string[];
  uses_portfolio: boolean;
  time_horizon: string | null;
  time_horizon_days: number | null;
  year_from: number | null;
  year_to: number | null;
  topics: string[];
  analysis_steps: AnalysisStep[];
  confidence: number;
  parser: "llm" | "rules";
  llm_model: string | null;
  supported: boolean;
  warnings: string[];
}

export interface QueryParseResponse {
  query: string;
  parsed: ParsedQuery;
  notice: string | null;
}
