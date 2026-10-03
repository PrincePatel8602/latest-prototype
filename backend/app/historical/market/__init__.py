"""Historical market / macro series (Phase 12 data layer).

Same layering as the storm dataset, one pipeline per source:

    raw payload (kept, sha256)  ->  clean (per-source parser + report)  ->  common daily observation
    ->  PostgreSQL (market_series + market_observations)

Nothing here computes returns or impact; that is the later event-study step.
"""
