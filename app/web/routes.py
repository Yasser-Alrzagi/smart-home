"""Local-asset Arabic UI. Bearer tokens stay in browser memory, never storage."""

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from app.core.config import settings

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=settings.templates_path)


@router.get("/app")
@router.get("/app/")
def interface(request: Request):
    response = templates.TemplateResponse(
        request=request, name="index.html", context={"api_base": settings.API_V1_STR}
    )
    response.headers["Cache-Control"] = "no-store"
    policy = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
    if not settings.DEBUG:
        policy += "; frame-ancestors 'self'"
    response.headers["Content-Security-Policy"] = policy
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
