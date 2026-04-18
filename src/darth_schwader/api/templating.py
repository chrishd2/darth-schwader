from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "ui" / "templates"
TEMPLATES = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def render_partial(request: Request, name: str, context: dict[str, object]) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name=name,
        context={"request": request, **context},
    )


__all__ = ["TEMPLATES", "is_htmx", "render_partial"]
