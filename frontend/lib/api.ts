import type { HealthResponse } from "@/types/health";
import type { DashboardSummary, DataCoverage, HistoricalStatus, MarketResponse, PriceSeriesResponse, NewsResponse, PortfolioResponse, WeatherResponse } from "@/types/api";
import type { ParsedQuery, QueryParseResponse } from "@/types/query";
import type { QueryPipelineResponse, RiskDrivers } from "@/types/agents";
import type { WeatherAgentResponse } from "@/types/weather";

// Only a URL - safe to expose. Secrets stay in the backend.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// One place for fetch + error handling, so every endpoint behaves the same.
async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Backend responded ${res.status} for ${path}`);
  return res.json() as Promise<T>;
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  // 422 = the backend's validation rejected the input; give a human message.
  if (res.status === 422) throw new Error("That question was not accepted (it must be 3-500 characters).");
  if (!res.ok) throw new Error(`Backend responded ${res.status} for ${path}`);
  return res.json() as Promise<T>;
}

export const getDashboardSummary = () => apiGet<DashboardSummary>("/api/dashboard/summary");
export const getHealth = () => apiGet<HealthResponse>("/api/health");
export const getPortfolio = () => apiGet<PortfolioResponse>("/api/portfolio");
export const getMarket = () => apiGet<MarketResponse>("/api/market");
export const getWeather = () => apiGet<WeatherResponse>("/api/weather");
export const getNews = () => apiGet<NewsResponse>("/api/news");
export const parseQuery = (query: string) => apiPost<QueryParseResponse>("/api/query/parse", { query });
// Phase 6: send the ALREADY-PARSED query so the question is not parsed (or sent to an LLM) twice.
export const analyzeWeather = (parsed: ParsedQuery) =>
  apiPost<WeatherAgentResponse>("/api/weather/analyze", { parsed });
// Phase 7/8: the full pipeline (understanding + only the agents the question needs) in ONE call.
export const runQuery = (query: string) => apiPost<QueryPipelineResponse>("/api/query", { query });

// Read-only views of stored history (PostgreSQL) used by the charts.
export const getRiskDrivers = () => apiGet<RiskDrivers>("/api/insights/risk-drivers");
export const getPrices = (symbols: string, days = 252) => apiGet<PriceSeriesResponse>(`/api/insights/prices?symbols=${encodeURIComponent(symbols)}&days=${days}`);
export const getCoverage = () => apiGet<DataCoverage>("/api/insights/data-coverage");
export const getHistoricalStatus = () => apiGet<HistoricalStatus>("/api/historical/status");
