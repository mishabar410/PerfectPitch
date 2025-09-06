# PerfectPitch MVP API

Minimal pipeline to analyze a pitch presentation using PPTX and audio transcript (OpenAI Whisper) and produce a JSON report, feedback, and questions.

## Stack
- FastAPI, Uvicorn
- OpenAI API: whisper-1 for transcription, gpt-4o-mini for judging
- python-pptx for parsing slides

## Setup

1) Python 3.11+ recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Set the OpenAI key:
```bash
export OPENAI_API_KEY=sk-...
```

## Run
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Artifacts are served under `/artifacts/*`.

## Folder layout
```
uploads/
  {uuid}/
    data.json      # slides with start_ms/end_ms (MVP uses heuristic)
    meta.json
    pptx.pptm or .pptx
    video.mp4 or audio.*
artifacts/
  {uuid}/report.json
  {uuid}/feedback.md
  {uuid}/questions.json
```

## API
- POST `/process/{uuid}` → runs pipeline, writes artifacts and returns their paths.
- GET `/artifacts/{uuid}/report.json` → retrieve report.
- GET `/health` → health check.

## Notes
- Transcript slicing is heuristic in MVP (full transcript per slide). You can upgrade by enabling segment timestamps and mapping to data.json windows.
- PPTX metrics include text density, min font size, contrast heuristic, style consistency. No CV required.

## Modules (overview)
- `app/main.py`: FastAPI app, mounts `/artifacts`, `/ui`, includes routers.
- `app/core/paths.py`: central paths for `uploads/`, `artifacts/`, `web/`.
- `app/services/pptx_parser.py`: parse PPTX texts and compute presentation metrics.
- `app/services/pptx_render.py`: render PPTX to PNG (LibreOffice/poppler).
- `app/services/transcription.py`: Whisper transcription helper.
- `app/services/judge.py`: LLM judging (multimodal image+text) and feedback.
- `app/services/tasks.py`: background pipeline and task status store.
- Routers: `sessions.py`, `uploads.py`, `audio.py`, `slides.py`, `process.py`, `status.py`.
- UI: `web/index.html` minimal interface for upload/record/browse/start.
