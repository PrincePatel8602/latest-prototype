from app.schemas.historical import HistoricalIntelligence
from app.schemas.query import ParsedQuery
from app.services.historical_service import search


def run_historical_agent(parsed: ParsedQuery) -> HistoricalIntelligence:
    return search(
        event_type=parsed.event_type,
        region=parsed.region,
        category=parsed.event_category,
        sectors=list(parsed.sectors),
        query=" ".join([parsed.region or "", parsed.event_type, *parsed.assets, *parsed.sectors]),
        year_from=parsed.year_from, year_to=parsed.year_to, topics=list(parsed.topics),
    )
