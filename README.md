# PerfectPitch MVP API

Minimal pipeline to analyze a pitch presentation using PPTX and audio transcript (OpenAI Whisper) and produce a JSON report, feedback, questions, and speech-quality metrics.

## Stack
- FastAPI, Uvicorn
- LLMs via OpenRouter (gpt-4o-mini for judging/feedback), ASR via OpenAI Whisper
- python-pptx (parsing), LibreOffice+poppler+pdf2image (slide PNGs)
- librosa+ffmpeg (speech quality)

## Setup

1) Python 3.11+ recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Set API keys (OpenRouter for chat; OpenAI for Whisper):
```bash
export OPENROUTER_API_KEY=or-...
export OPENAI_API_KEY=sk-...
# optional for OpenRouter analytics
export OPENROUTER_HTTP_REFERER=https://your.app/
export OPENROUTER_X_TITLE="PerfectPitch"
```

## Run
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Artifacts are served under `/artifacts/*`. Static UI at `/ui/`.

## Folder layout
```
uploads/
  {uuid}/
    data.json      # slides with start_ms/end_ms (MVP uses heuristic)
    meta.json
    pptx.pptm or .pptx
    video.mp4 or audio.*
    word.docx|script.docx (optional)
artifacts/
  {uuid}/report.json
  {uuid}/feedback.md
  {uuid}/questions.json
```

## API
- POST `/sessions` → create upload session (UI does this automatically on load).
- POST `/uploads/{uuid}` → upload files (pptx, meta.json, data.json, word.docx).
- POST `/audio/{uuid}/chunk` + `/audio/{uuid}/finalize` → stream mic recording.
- POST `/process/{uuid}` → run analysis in background.
- GET `/status/{task_id}` → task progress.
- GET `/artifacts/{uuid}/report.json|feedback.md|questions.json` → results.

## Notes
- UI: upload PPTX, it auto-renders PNG previews; navigate slides while recording. Timeline is saved to `data.json` automatically on stop.
- Transcript slicing uses `data.json` slide timings when present, otherwise heuristic.
- Report includes:
  - `slides.per_slide[]`: similarity, judgement, evidence, transcript, duration_ms
  - `presentation_quality`: density/small_fonts/contrast/style
  - `questions` and `feedback`
  - `script`: presence + eval of script vs speech + script quality (if Word uploaded)
  - `speech_quality`: overall WPM/pauses/fillers/pitch and per-slide details

## Modules (overview)
- `app/main.py`: FastAPI app, mounts `/artifacts`, `/ui`, includes routers.
- `app/core/paths.py`: central paths for `uploads/`, `artifacts/`, `web/`.
- `app/services/pptx_parser.py`: parse PPTX texts and compute presentation metrics.
- `app/services/pptx_render.py`: render PPTX to PNG (LibreOffice/poppler).
- `app/services/transcription.py`: Whisper transcription helper.
- `app/services/judge.py`: LLM judging (multimodal image+text), feedback, script checks.
- `app/services/tasks.py`: background pipeline and task status store.
- `app/services/speech_quality.py`: speech metrics (WPM, pauses, fillers, pitch).
- `app/services/doc_parser.py`: Word (.docx/.docm) script parser.
- Routers: `sessions.py`, `uploads.py`, `audio.py`, `slides.py`, `process.py`, `status.py`.
- UI: `web/index.html` minimal interface for upload/record/browse/start.
