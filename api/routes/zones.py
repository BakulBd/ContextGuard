from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from contextguard.zones import Zone

from ..schemas import ZoneIn, ZoneOut
from ..security import require_api_key
from ..state import get_service

router = APIRouter(prefix="/zones", tags=["zones"], dependencies=[Depends(require_api_key)])

# All three routes operate on the SAME ZoneManager instance the running
# pipeline holds (service.pipeline.zones), not a freshly re-read copy
# from disk -- one source of truth, so a create/delete is visible to
# both the next list_zones() call and the live pipeline immediately,
# with no separate reload step needed (unlike the dashboard, which
# edits a disk file from a fresh Streamlit rerun each time and has to
# explicitly reload_zones() afterwards).


@router.get("", response_model=list[ZoneOut])
def list_zones() -> list[ZoneOut]:
    zm = get_service().pipeline.zones
    return [ZoneOut(name=z.name, kind=z.kind, polygon=z.polygon) for z in zm.zones]


@router.post("", response_model=ZoneOut, status_code=201)
def create_zone(zone_in: ZoneIn) -> ZoneOut:
    zm = get_service().pipeline.zones
    try:
        zone = Zone(name=zone_in.name, kind=zone_in.kind, polygon=zone_in.polygon)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    zm.add(zone)
    if zm.path:
        zm.save()
    return ZoneOut(name=zone.name, kind=zone.kind, polygon=zone.polygon)


@router.delete("/{name}", status_code=204)
def delete_zone(name: str) -> None:
    zm = get_service().pipeline.zones
    if zm.get(name) is None:
        raise HTTPException(status_code=404, detail="zone not found")
    zm.remove(name)
    if zm.path:
        zm.save()
