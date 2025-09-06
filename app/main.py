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
from app.routers.process import router as process_router
from app.routers.sessions import router as sessions_router
from app.routers.uploads import router as uploads_router
from app.routers.audio import router as audio_router
from app.routers.status import router as status_router
from app.routers.slides import router as slides_router


app = FastAPI(title="PerfectPitch MVP API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/artifacts", StaticFiles(directory=str(ARTIFACTS_DIR), html=False), name="artifacts")
app.mount("/ui", StaticFiles(directory=str(WEB_DIR), html=True), name="ui")


@app.get("/health")
def health():
    return {"ok": True}


app.include_router(sessions_router)
app.include_router(uploads_router)
app.include_router(audio_router)
app.include_router(process_router)
app.include_router(status_router)
app.include_router(slides_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)


