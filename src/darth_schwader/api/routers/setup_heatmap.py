from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from darth_schwader.api.templating import is_htmx, render_partial
from darth_schwader.services.setup_heatmap import heatmap_row_to_dict

router = APIRouter(tags=["setup-heatmap"])


@router.get("/setup-heatmap", response_model=None)
async def get_setup_heatmap(
    request: Request,
) -> list[dict[str, object]] | HTMLResponse:
    service = request.app.state.setup_heatmap_service
    rows = await service.snapshot()
    payload = [heatmap_row_to_dict(row) for row in rows]
    if is_htmx(request):
        return render_partial(
            request,
            "partials/_setup_heatmap.html",
            {"rows": payload},
        )
    return payload


__all__ = ["router"]
