from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from contextguard.nlp.query import NLQueryEngine

from ..schemas import QueryIn, QueryOut
from ..security import limiter, require_api_key
from ..state import get_service
from .events import to_out

router = APIRouter(prefix="/query", tags=["query"], dependencies=[Depends(require_api_key)])


@router.post("", response_model=QueryOut)
@limiter.limit("20/minute")  # NLP work is heavier than a plain row fetch -- stricter than the global default
def ask(request: Request, query_in: QueryIn) -> QueryOut:
    service = get_service()
    zone_names = [z.name for z in service.pipeline.zones.zones]
    engine = NLQueryEngine(zone_names=zone_names, risk_thresholds=service.config.risk_thresholds)
    result = engine.answer(query_in.question, service.pipeline.store)
    return QueryOut(
        text=result.text,
        intent=result.parsed.intent,
        filters=result.parsed.filters,
        rows=[to_out(e) for e in result.rows],
    )
