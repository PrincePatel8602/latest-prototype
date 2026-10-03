// Short, human labels for stored series and categories.
export const SERIES_SHORT: Record<string, string> = {
  "yahoo:XOM": "XOM", "yahoo:CVX": "CVX", "yahoo:XLE": "Energy sector", "eia:RWTC": "Oil (WTI)", "eia:RNGWHHD": "Natural gas",
};

export const categoryShort = (c: number | null | undefined) => (c == null ? "n/a" : c >= 1 ? `Cat ${c}` : c === 0 ? "TS" : "TD");
