"""LLM judging and feedback generation services.

judge_slides_batched supports multimodal scoring with slide images.
generate_feedback_and_questions aggregates deck-level advice and Q&A.
"""

import json
import base64
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from .openai_client import client
import re
from openai import OpenAI

def slice_transcript_by_datajson(full_text: str, data_json: Dict[str, Any]) -> Dict[int, str]:
    """Return mapping of slide index to transcript window (MVP heuristic)."""
    chunks: Dict[int, str] = {}
    for sl in data_json.get("slides", []):
        idx = int(sl.get("index"))
        chunks[idx] = full_text
    return chunks



client = OpenAI()

def judge_slides_batched(
    slides: List[Dict[str, Any]],
    index_to_transcript: Dict[int, str],
    batch_size: int = 3,
    image_path_by_index: Optional[Dict[int, Path]] = None,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for i in range(0, len(slides), batch_size):
        batch = slides[i : i + batch_size]

        system = (
            "You are a rigorous presentation reviewer. "
            "Return strictly valid JSON with per_slide results. "
            "Judge alignment between the slide IMAGE and what the speaker says. "
            "Output strictly valid JSON only."
        )

        # Build multimodal message content: text + optional image for each slide
        user_content: List[Dict[str, Any]] = []
        for sl in batch:
            idx = sl["index"]
            transcript_text = index_to_transcript.get(idx, "")
            user_content.append({"type": "text", "text": f"[SLIDE {idx}]"})

            if image_path_by_index and idx in image_path_by_index and image_path_by_index[idx].exists():
                try:
                    b = image_path_by_index[idx].read_bytes()
                    b64 = base64.b64encode(b).decode("ascii")
                    data_uri = f"data:image/png;base64,{b64}"
                    user_content.append({"type": "image_url", "image_url": {"url": data_uri}})
                except Exception:
                    pass

            instruct = (
                "[TRANSCRIPT_WINDOW]\n" + transcript_text +
                "\n[INSTRUCTIONS]\nFor this slide, return JSON with keys: "
                "similarity_0_1 (0..1), judgement (RU, 1-2 sentences), missing_points[], hallucinated_points[], evidence[]."
            )
            user_content.append({"type": "text", "text": instruct})

        # Final instruction: aggregate
        user_content.append({"type": "text", "text": "Return {\"per_slide\":[{index, similarity_0_1, judgement, missing_points, hallucinated_points, evidence}]}, preserving input order by slide index."})

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": [{"type": "text", "text": system}]},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
        )

        txt = (resp.choices[0].message.content or "").strip()
        try:
            parsed = json.loads(txt)
            batch_results = parsed.get("per_slide", [])
        except Exception:
            batch_results = []

        title_by_index = {sl["index"]: sl.get("title", f"Slide {sl['index']}") for sl in batch}
        for r in batch_results:
            r["slide_title"] = title_by_index.get(r.get("index"), "")
        results.extend(batch_results)

    return results


def generate_feedback_and_questions(
    weak_slides: List[int],
    deck_metrics: Dict[str, Any],
    per_slide: List[Dict[str, Any]],
) -> Tuple[List[str], Dict[str, List[Dict[str, Any]]]]:
    """Generate actionable improvements and role-based questions via LLM."""
    system = (
        "You are a senior coach for public speaking. Be concise, actionable, and specific. "
        "Output strictly valid JSON only."
    )
    context = {
        "weak_slides": weak_slides,
        "style_issues": deck_metrics,
        "per_slide_similarities": [
            {
                "index": r.get("index"),
                "similarity_0_1": r.get("similarity_0_1", 0.0),
                "judgement": r.get("judgement", ""),
            }
            for r in per_slide
        ],
    }
    user = (
        "[CONTEXT]\n" + json.dumps(context, ensure_ascii=False) +
        "\n[TASK]\n1) Summarize 5–8 concrete improvements (Russian).\n"
        "2) Generate 5 investor, 5 tech, 5 product challenge questions, referencing slide numbers where relevant.\n"
        "Return JSON: { \"improvements\": [str], \"questions\": {\"investor\":[str], \"tech\":[str], \"product\":[str]} }"
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
    )

    txt = (resp.choices[0].message.content or "").strip()
    try:
        parsed = json.loads(txt)
        improvements = parsed.get("improvements", [])
        qs = parsed.get("questions", {})
    except Exception:
        improvements = []
        qs = {"investor": [], "tech": [], "product": []}

    def _wrap_questions(lst: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for q in lst:
            slide_num = None
            m = re.search(r"(?:slide|слайд)\s*(\d+)", q, flags=re.IGNORECASE)
            if m:
                try:
                    slide_num = int(m.group(1))
                except Exception:
                    slide_num = None
            out.append({"slide": slide_num, "q": q})
        return out

    questions_struct = {
        "investor": _wrap_questions(qs.get("investor", [])[:5]),
        "tech": _wrap_questions(qs.get("tech", [])[:5]),
        "product": _wrap_questions(qs.get("product", [])[:5]),
    }
    return improvements[:8], questions_struct