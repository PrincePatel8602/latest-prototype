// Mirrors backend/app/schemas/news.py, market.py and pipeline.py (Phase 7/8).
import type { DataMeta, Sentiment, SentimentMethod } from "@/types/api";
import type { ParsedQuery } from "@/types/query";
import type { WeatherIntelligence } from "@/types/weather";

export type Relevance = "high" | "medium" | "low";
export type NewsStatus = "ok" | "no_results" | "error";

export interface NewsRequest {
  event_type: string; region: string | null; sectors: string[]; assets: string[];
  event_terms: string[]; region_terms: string[]; market_terms: string[];
  search_query: string | null;
}
export interface NewsArticle {
  id: string; title: string; source_name: string; url: string | null; published_at: string | null;
  summary: string | null; related_asset: string | null; sentiment: Sentiment; sentiment_score: number;
  relevance: Relevance; matched_terms: string[];
}
export interface NewsIntelligence {
  meta: DataMeta | null; status: NewsStatus; request: NewsRequest; articles: NewsArticle[];
  aggregate_score: number | null; aggregate_sentiment: Sentiment | null;
  sentiment_method: SentimentMethod | null; notices: string[]; summary: string;
}

export type MarketStatus = "ok" | "partial" | "no_data" | "no_assets" | "error";
export interface MarketRequest {
  intent: string; uses_portfolio: boolean; sectors: string[]; requested_assets: string[]; symbols: string[];
}
export interface MarketAsset {
  symbol: string; name: string; kind: "equity" | "etf" | "commodity"; sector: string | null;
  available: boolean; price: number | null; change: number | null; change_pct: number | null;
  as_of: string | null; in_portfolio: boolean; reasons: string[]; note: string | null;
}
export interface MarketIntelligence {
  meta: DataMeta | null; status: MarketStatus; request: MarketRequest; assets: MarketAsset[];
  notices: string[]; summary: string;
}

export type RunStatus = "completed" | "failed" | "not_implemented";
export interface AgentRun { step: string; status: RunStatus; note: string | null }

export interface DistributionStats {
  n: number; median: number | null; mean: number | null; p10: number | null; p90: number | null;
  share_positive: number | null; mean_ci_low: number | null; mean_ci_high: number | null;
  grade: "insufficient_data" | "not_distinguishable_from_zero" | "weak_signal" | "indicative";
}
export interface FusionAsset {
  symbol: string; series_key: string | null; weight_pct: number; covered: boolean; stats: DistributionStats | null;
  scenario_shock_pct: number | null; scenario_vs_history: string | null;
}
export interface FusionAssessment {
  meta: DataMeta; status: string; event: Record<string, unknown>;
  analogs: { n_selected?: number; n_with_joint_results?: number; source?: string };
  assets: FusionAsset[];
  portfolio: {
    symbols: string[]; covered_weight_pct: number; uncovered_weight_pct: number; basis: string;
    all_analogs: DistributionStats; independent_only: DistributionStats;
    per_storm: { storm_id: string; label: string; year: number; value_pct: number; independent: boolean }[];
    median_usd: number | null; p10_usd: number | null; p90_usd: number | null;
    scenario_change_pct: number | null; scenario_vs_history: string | null;
  } | null;
  historical_risk: { days: number; end: string; annualised_volatility_pct: number; var95_1d_pct: number } | null;
  context_layers: { layer: string; status: string; summary: string; used_in_estimate: boolean; reason: string }[];
  conclusion: string; limitations: string[];
}

export interface RiskDrivers {
  meta: DataMeta; status: string; prices_as_of: string | null; prices_stale: boolean;
  rolling_volatility: { date: string; vol_pct: number }[];
  concentration: { hhi?: number; largest_position?: string; largest_position_pct?: number; energy_exposure_pct?: number };
  covered_weight_pct: number; uncovered_weight_pct: number;
  risk_change: {
    window_days: number; recent_vol_pct: number; year_vol_pct: number; vol_ratio: number | null;
    history_percentile: number; history_days: number; classification: "elevated" | "typical" | "subdued";
    sleeve_return_recent_pct: number;
  } | null;
  holdings: { symbol: string; weight_pct: number; risk_share_recent_pct: number; risk_share_year_pct: number;
    return_recent_pct: number; volatility_recent_pct: number; volatility_year_pct: number }[];
  context_layers: { layer: string; status: string; summary: string; used_in_estimate: boolean; reason: string }[];
  conclusion: string; limitations: string[];
}

export interface SummaryStats {
  n: number; median: number | null; p10: number | null; p90: number | null;
}
export interface HedgeCandidate {
  rank: number | null; series_key: string; name: string; kind: string; status: "ok" | "insufficient_history";
  position: string; hedge_ratio: number | null; notional_usd: number | null; notional_pct_of_portfolio: number | null;
  correlation: number | null; in_sample_variance_reduction_pct: number | null;
  out_of_sample: { train_days: number; test_days: number; variance_reduction_pct: number } | null;
  before: { volatility_pct: number; var95_1d_pct: number; worst_day_pct: number } | null;
  after: { volatility_pct: number; var95_1d_pct: number; worst_day_pct: number } | null;
  storm_windows: { n: number; unhedged: SummaryStats; hedged: SummaryStats } | null;
  note: string;
}
export interface HedgingAnalysis {
  meta: DataMeta; status: string; basis: Record<string, unknown>; candidates: HedgeCandidate[];
  trim_options: { symbol: string; trim_fraction: number; weight_before_pct: number; weight_after_pct: number;
    volatility_before_pct: number; volatility_after_pct: number; volatility_reduction_pct: number }[];
  not_modeled: string[]; conclusion: string; limitations: string[];
}

export interface QueryPipelineResponse {
  query: string; parsed: ParsedQuery; parse_notice: string | null;
  weather: WeatherIntelligence | null; news: NewsIntelligence | null; market: MarketIntelligence | null;
  historical: HistoricalIntelligence | null; exposure: ExposureAnalysis | null;
  scenario: ScenarioAnalysis | null; risk: RiskAnalysis | null; drivers: RiskDrivers | null; fusion: FusionAssessment | null; hedging: HedgingAnalysis | null;
  steps: AgentRun[]; orchestrator: string;
}


export interface HistoricalStorm {
  postgres_id: number; event_id: string; storm_id: string; name: string; year: number;
  basin: string; region: string; event_type: string; start_datetime: string; end_datetime: string;
  duration_hours: number | null; max_wind_kt: number | null; max_wind_mph: number | null;
  min_pressure_mb: number | null; max_category_normalized: number | null; max_category_original: number | null;
  category_source: string | null; track_length_km: number | null; n_observations: number;
  gulf_of_mexico_entered: boolean; max_category_in_gulf: number | null; data_quality_status: string;
  provenance: {
    source: string; dataset_version: string; source_url: string; subset: string; source_record_id: string;
    postgres: { table: string; id: number }; pinecone: { namespace: string; record_id: string; in_sync: boolean } | null;
  };
}
export interface MarketResponse {
  series_key: string; name: string; status: string; detail: string | null; window: string;
  car: number | null; t_stat: number | null; t0_date: string | null; overlap: boolean;
  provenance: { benchmark?: string };
}
export interface PhysicalImpact {
  max_oil_shut_in_pct: number | null; max_gas_shut_in_pct: number | null; max_platforms_evacuated: number | null;
  peak_oil_date: string | null; n_reports_used: number; n_reports_listed: number; source: string;
  source_urls: string[]; note: string;
}
export interface HistoricalMatch {
  storm: HistoricalStorm; market_response: MarketResponse[]; physical_impact: PhysicalImpact | null; retrieval_method: string; similarity_score: number | null; match_reasons: string[];
}
export interface HistoricalIntelligence {
  meta: DataMeta; status: string; query: Record<string, unknown>; matches: HistoricalMatch[];
  retrieval_method: string; semantic_status: string; market_response_note: string | null;
  dataset: { source?: string; dataset_version?: string; storms_in_database?: number; last_ingestion?: string | null };
  notices: string[]; summary: string;
}
export interface ExposureItem { symbol: string; name: string; sector: string; weight_pct: number; value_usd: number }
export interface ExposureAnalysis {
  meta: DataMeta; total_value: number; energy_exposure_pct: number; largest_position_pct: number;
  concentration_hhi: number; holdings: ExposureItem[]; summary: string;
}
export interface ScenarioImpact {
  symbol: string; shock_pct: number; contribution_pct: number; contribution_usd: number; assumption: string
}
export interface ScenarioAnalysis {
  meta: DataMeta; name: string; assumptions: string[]; impacts: ScenarioImpact[];
  estimated_portfolio_change_pct: number; estimated_portfolio_change_usd: number; summary: string;
}
export interface RiskAnalysis {
  meta: DataMeta; risk_level: string; risk_score: number; volatility_pct: number | null; volatility_method: string;
  concentration_score: number; scenario_change_pct: number | null; scenario_change_usd: number | null;
  historical_var_95_pct: number | null; historical_var_method: string; limitations: string[]; summary: string;
}
