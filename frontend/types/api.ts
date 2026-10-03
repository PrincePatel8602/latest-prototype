// Mirrors backend/app/schemas/*.py - keep in sync when a schema changes.
export interface DataMeta {
  source: "live" | "demo" | "user";
  notice: string | null;
  as_of: string; // ISO timestamp
}

export interface Holding { symbol: string; name: string; sector: string; weight_pct: number; value_usd: number }
export interface SectorExposure { sector: string; weight_pct: number; value_usd: number }
export interface DashboardSummary {
  risk: {
    status: string; note: string | null; classification?: "elevated" | "typical" | "subdued";
    recent_vol_pct?: number; year_vol_pct?: number; history_percentile?: number; window_days?: number;
    prices_as_of?: string; top_risk_symbol?: string | null; covered_weight_pct?: number;
  };
  hurricane_impact: {
    status: string; note: string | null; reference_event: string; n_storms?: number; median_pct?: number;
    p10_pct?: number; p90_pct?: number; grade?: string; median_usd?: number; p10_usd?: number; p90_usd?: number;
    covered_weight_pct?: number; storms?: { storm_id: string; label: string; year: number; value_pct: number; independent: boolean }[];
  };
}

export interface PortfolioResponse {
  meta: DataMeta; name: string; total_value: number;
  holdings: Holding[]; sector_exposure: SectorExposure[]; energy_exposure_pct: number;
}

export interface Quote {
  symbol: string; name: string; kind: "equity" | "etf" | "commodity"; price: number; change_pct: number;
  change?: number | null; as_of?: string | null; // Phase 7, optional
}
export interface MarketResponse { meta: DataMeta; quotes: Quote[] }

export interface ForecastPoint { hours_ahead: number; lat: number; lon: number; wind_mph: number }
export interface WeatherEvent {
  id: string; event_type: "hurricane" | "tropical_storm"; name: string; category: number; wind_mph: number;
  region: string; lat: number; lon: number; forecast_path: ForecastPoint[];
  affected_regions: string[]; affected_infrastructure: string[]; affected_sectors: string[];
  severity: "LOW" | "MODERATE" | "HIGH" | "EXTREME";
  // Phase 6 additions
  forecast_available: boolean; // true only if forecast_path really extends beyond "now"
  data_source: string;
  last_update: string | null; // provider's own timestamp (null for demo)
  movement_dir_deg: number | null;
  movement_speed_mph: number | null;
  pressure_mb: number | null;
}
export interface WeatherResponse { meta: DataMeta; events: WeatherEvent[] }

export type Sentiment = "positive" | "neutral" | "negative";
export interface NewsItem {
  id: string; headline: string; publisher: string; url: string | null; published_at: string;
  related_asset: string; sentiment: Sentiment; sentiment_score: number; summary?: string | null;
}
// "lexicon" = transparent keyword heuristic (NOT an AI model); "demo" = fixed sample values.
export type SentimentMethod = "demo" | "lexicon";
export interface NewsResponse {
  meta: DataMeta; items: NewsItem[]; aggregate_score: number;
  aggregate_sentiment: Sentiment; sentiment_method: SentimentMethod;
}

export interface PriceSeriesResponse {
  base: number; note: string;
  series: { symbol: string; name: string; source: string; as_of: string; change_pct: number; points: [string, number][] }[];
}
export interface DataCoverage {
  storms: { count: number; track_points: number; source: string };
  market: { series: number; observations: number; detail: { series_key: string; name: string; source: string; category: string; first_date: string | null; last_date: string | null; observations: number }[] };
  shut_ins: { storms: number; reports: number; source: string };
  event_study: { results: number };
}
export interface HistoricalStatus {
  storms: number; pinecone: { configured: boolean; namespace: string | null; records: number | null };
  last_ingestion: { started_at: string; status: string; dataset_version: string; source: string; subset: string } | null;
}
