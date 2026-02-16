from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import SkillRunRequest

router = APIRouter(tags=["admin"])


@router.get("/memory/search")
def memory_search(request: Request, q: str = Query(min_length=1), top_k: int = Query(default=5, ge=1, le=20)) -> list[dict[str, object]]:
    return request.app.state.container.admin.search_memory(query=q, top_k=top_k)


@router.get("/skills")
def skills_list(request: Request) -> list[dict[str, object]]:
    return request.app.state.container.admin.skills()


@router.post("/skills/run")
def skills_run(body: SkillRunRequest, request: Request) -> dict[str, object]:
    try:
        return request.app.state.container.admin.run_skill(skill_id=body.skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/heartbeat/evaluate")
def heartbeat_evaluate(request: Request) -> dict[str, object]:
    return request.app.state.container.admin.evaluate_heartbeat()


@router.get("/heartbeat/history")
def heartbeat_history(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, object]]:
    return request.app.state.container.admin.heartbeat_history(limit=limit)


@router.get("/logs")
def logs(
    request: Request,
    source: str | None = Query(default=None),
    level: str | None = Query(default=None),
    process_name: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, object]:
    return {
        "source": source,
        "level": level,
        "process_name": process_name,
        "event_type": event_type,
        "q": q,
        "items": request.app.state.container.admin.logs(
            source=source,
            level=level,
            process_name=process_name,
            event_type=event_type,
            q=q,
            limit=limit,
        ),
    }
