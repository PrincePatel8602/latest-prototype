// What each real backend agent does, in plain language. Descriptions match the code (backend/app/agents, services).
// Nothing here is a status: live state always comes from the streamed run.

export type StepKey = "weather" | "news" | "market" | "historical" | "exposure" | "scenario" | "risk" | "drivers" | "fusion" | "hedging";
export type LaneId = "gather" | "analyze" | "synthesize";

export interface AgentInfo {
  key: StepKey; title: string; does: string; technical: string; sources: string[]; lane: LaneId;
}

export const LANES: { id: LaneId; title: string; blurb: string }[] = [
  { id: "gather", title: "Gather", blurb: "Now, and in the past" },
  { id: "analyze", title: "Analyze", blurb: "Your exposure and risk" },
  { id: "synthesize", title: "Synthesize", blurb: "Weigh evidence, test responses" },
];

export const AGENTS: Record<StepKey, AgentInfo> = {
  weather: { key: "weather", lane: "gather", title: "Weather", sources: ["NOAA Hurricane Center"],
    does: "Checks which tropical storms are active right now and whether they match your question.",
    technical: "Weather Agent: live NOAA National Hurricane Center feed. Current position and intensity only; no forecast track is invented." },
  news: { key: "news", lane: "gather", title: "News", sources: ["NewsAPI"],
    does: "Reads recent headlines about the event and scores their tone.",
    technical: "News Agent: NewsAPI boolean search, transparent relevance rules, keyword-lexicon sentiment (not an AI model)." },
  market: { key: "market", lane: "gather", title: "Markets", sources: ["Finnhub"],
    does: "Fetches current prices for the assets you hold or asked about.",
    technical: "Market Agent: Finnhub quotes for the assets the question points to. Quotes only." },
  historical: { key: "historical", lane: "gather", title: "History", sources: ["NOAA IBTrACS", "Pinecone", "PostgreSQL", "BSEE"],
    does: "Finds comparable past storms in 40+ years of records and shows what markets did around them.",
    technical: "Historical Agent: structured filters in PostgreSQL combined with semantic search in Pinecone over NOAA IBTrACS v04r01; attaches stored event-study results and BSEE shut-ins." },
  exposure: { key: "exposure", lane: "analyze", title: "Exposure", sources: ["Your portfolio"],
    does: "Measures how much of your portfolio sits in each sector.",
    technical: "Quant Agent: sector weights and concentration (HHI) computed in Python from the current portfolio." },
  scenario: { key: "scenario", lane: "analyze", title: "Stress test", sources: ["Model assumptions"],
    does: "Applies an illustrative shock to your holdings. It is an assumption, labelled as one.",
    technical: "Quant Agent: fixed illustrative hurricane shocks per holding. Not a forecast; later compared against measured history." },
  risk: { key: "risk", lane: "analyze", title: "Risk", sources: ["Stored price history"],
    does: "Calculates volatility and one-day loss risk from real price history.",
    technical: "Quant Agent: volatility and historical 95% VaR from stored daily returns (EIA, FRED, Yahoo Finance in PostgreSQL)." },
  drivers: { key: "drivers", lane: "analyze", title: "Risk drivers", sources: ["Stored price history"],
    does: "Checks whether your risk actually changed recently, and which holding is behind it.",
    technical: "Compares 20-day realised volatility with the past year and with its own 3-year history; variance share per holding." },
  fusion: { key: "fusion", lane: "synthesize", title: "Evidence", sources: ["Event studies", "NOAA IBTrACS"],
    does: "Compares what similar storms did to holdings like yours, and grades how reliable that evidence is.",
    technical: "Evidence Fusion: stored market-model event studies for analog storms, applied to your weights; bootstrap over storms; evidence grade from sample size and interval vs zero." },
  hedging: { key: "hedging", lane: "synthesize", title: "Hedging", sources: ["Stored price history", "Event studies"],
    does: "Tests which hedges would have reduced risk historically, and how stable that was.",
    technical: "Hedging Agent: minimum-variance hedge ratios, ranked by out-of-sample variance reduction; replayed through comparable storm windows." },
};

export const STEP_ORDER: StepKey[] = ["weather", "news", "market", "historical", "exposure", "scenario", "risk", "drivers", "fusion", "hedging"];

export const INTENT_LABEL: Record<string, string> = {
  event_impact: "Impact of an event", portfolio_risk: "Portfolio risk", historical_search: "Historical look-up", exposure: "Exposure",
  explain_risk: "Explain risk", hedging: "Hedging", other: "Not recognised",
};

export const DATA_SOURCES = [
  { name: "NOAA IBTrACS", detail: "Every North Atlantic storm since 1980: track, wind, pressure", kind: "history" },
  { name: "NOAA Hurricane Center", detail: "Live position of active tropical systems", kind: "live" },
  { name: "NewsAPI", detail: "Recent headlines", kind: "live" },
  { name: "Finnhub", detail: "Current quotes", kind: "live" },
  { name: "EIA · FRED · Yahoo Finance", detail: "Decades of oil, gas, equity and macro prices", kind: "history" },
  { name: "BSEE", detail: "Gulf of Mexico production shut-ins during storms", kind: "history" },
  { name: "Pinecone + PostgreSQL", detail: "Semantic search and the structured record", kind: "store" },
] as const;
