"""FastAPI app entrypoint.

Exposes:
- Static artifacts at /artifacts
- Static UI at /ui
- API routers: sessions, uploads, audio, slides, process, status
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from app.core.paths import ARTIFACTS_DIR, WEB_DIR
from app.core.logging import setup_logging, request_id_var
from app.routers.process import router as process_router
from app.routers.sessions import router as sessions_router
from app.routers.uploads import router as uploads_router
from app.routers.audio import router as audio_router
from app.routers.status import router as status_router
from app.routers.slides import router as slides_router
from app.routers.text import router as text_router
from app.routers.questions import router as questions_router


setup_logging()
app = FastAPI(title="PerfectPitch MVP API")
import json
def _allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "*")
    if raw.strip() == "*":
        return ["*"]
    try:
        return [s.strip() for s in raw.split(",") if s.strip()]
    except Exception:
        return ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/artifacts", StaticFiles(directory=str(ARTIFACTS_DIR), html=False), name="artifacts")
app.mount("/ui", StaticFiles(directory=str(WEB_DIR), html=True), name="ui")
from fastapi import Request
import uuid



@app.get("/health")
def health():
    # Dependency checks
    def has_bin(name: str) -> bool:
        try:
            import shutil
            return shutil.which(name) is not None
        except Exception:
            return False

    # poppler is used by pdf2image; no reliable import check, but 'pdftoppm' binary indicates presence
    deps = {
        "ffmpeg": has_bin("ffmpeg"),
        "soffice": has_bin("soffice") or has_bin("libreoffice"),
        "poppler_pdftoppm": has_bin("pdftoppm"),
        "openai_key": bool(os.getenv("OPENAI_API_KEY")),
    }
    return {"ok": True, "deps": deps}


app.include_router(sessions_router)
app.include_router(uploads_router)
app.include_router(audio_router)
app.include_router(process_router)
app.include_router(status_router)
app.include_router(slides_router)
app.include_router(text_router)
app.include_router(questions_router)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id_var.set(rid)
    try:
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response
    finally:
        request_id_var.reset(token)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)


