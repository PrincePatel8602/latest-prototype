"""AEGIS historical-data foundation (Phase 11).

Layering (each layer only talks to the one below it):

    raw (NOAA CSV, never modified)
      -> ibtracs.parse      dataset-specific parsing
      -> ibtracs.clean      validation / cleaning / quality report
      -> categories         category normalisation (original value is preserved)
      -> ibtracs.aggregate  storm-level deterministic features (pure Python, no LLM)
      -> events             common HistoricalEvent representation + search document
      -> repository         PostgreSQL (source of truth)
      -> vector_store       Pinecone (semantic retrieval only)
      -> search             structured filter + semantic retrieval, hydrated from PostgreSQL

A future dataset (prices, news, macro...) gets its own sub-package next to ibtracs and
emits the same HistoricalEvent / its own normalised table. Nothing here knows about
market impact.
"""
