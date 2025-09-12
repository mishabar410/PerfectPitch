"""LLM judging and feedback generation services.

judge_slides_batched supports multimodal scoring with slide images.
generate_feedback_and_questions aggregates deck-level advice and Q&A.
"""

import json
import logging
import base64
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from .openai_client import client
import re

def slice_transcript_by_datajson(full_text: str, data_json: Dict[str, Any]) -> Dict[int, str]:
    """Return mapping of slide index to transcript window.

    Heuristic: split the full transcript into word-based chunks proportionally to
    slide durations from data.json (start_ms..end_ms). If timings are missing,
    split evenly by number of slides.
    """
    slides = [s for s in (data_json.get("slides") or []) if s is not None]
    if not slides:
        return {}

    # Tokenize transcript into words preserving simple whitespace separation
    words = re.findall(r"\S+", full_text or "")
    total_words = len(words)
    if total_words == 0:
        # Empty transcript → return empty windows for each slide
        return {int(s.get("index")): "" for s in slides if s.get("index") is not None}

    # Compute durations where available
    durations: list[tuple[int, int]] = []  # (slide_index, duration_ms)
    total_duration_ms = 0
    for s in slides:
        try:
            idx = int(s.get("index"))
        except Exception:
            continue
        try:
            start_ms = s.get("start_ms")
            end_ms = s.get("end_ms")
            if start_ms is None or end_ms is None:
                durations.append((idx, -1))
                continue
            dur = int(end_ms) - int(start_ms)
            if dur <= 0:
                durations.append((idx, -1))
                continue
            durations.append((idx, dur))
            total_duration_ms += dur
        except Exception:
            durations.append((idx, -1))

    # Decide allocation strategy
    allocations: Dict[int, int] = {}
    if total_duration_ms > 0 and any(d >= 0 for _, d in durations):
        # Proportional allocation by duration
        remaining_words = total_words
        remaining_ms = total_duration_ms
        for i, (idx, dur) in enumerate(durations):
            if dur <= 0:
                allocations[idx] = 0
                continue
            if i == len(durations) - 1:
                # assign all remaining to last with valid duration
                allocations[idx] = remaining_words
            else:
                w = round(total_words * (dur / total_duration_ms))
                w = max(0, min(remaining_words, w))
                allocations[idx] = w
                remaining_words -= w
                remaining_ms -= dur
        # if some words remain due to rounding and last had invalid duration, append to last slide overall
        if sum(allocations.values()) < total_words:
            last_key = durations[-1][0] if durations else None
            if last_key is not None:
                allocations[last_key] = allocations.get(last_key, 0) + (total_words - sum(allocations.values()))
    else:
        # Even split across slides
        n = max(1, len(durations))
        base = total_words // n
        rem = total_words % n
        for i, (idx, _) in enumerate(durations):
            allocations[idx] = base + (1 if i < rem else 0)

    # Build text chunks in slide order (preserve given ordering)
    chunks: Dict[int, str] = {}
    cursor = 0
    for idx, _ in durations:
        take = max(0, int(allocations.get(idx, 0)))
        if take <= 0:
            chunks[idx] = ""
            continue
        segment = words[cursor : cursor + take]
        chunks[idx] = " ".join(segment)
        cursor += take
    # Any leftover words (due to rounding) go to the last slide
    if cursor < total_words and durations:
        last_idx = durations[-1][0]
        leftover = words[cursor:]
        chunks[last_idx] = (chunks.get(last_idx, "") + (" " if chunks.get(last_idx) else "") + " ".join(leftover)).strip()
    return chunks




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
    logging.getLogger(__name__).info("judge_feedback_questions", extra={"improvements": len(improvements), "q_investor": len(qs.get("investor", [])), "q_tech": len(qs.get("tech", [])), "q_product": len(qs.get("product", []))})

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


def judge_script_vs_speech(script_text: str, transcript_text: str) -> Dict[str, Any]:
    """Compare provided script (Word text) against spoken transcript.

    Returns JSON with similarity, omissions, additions, and brief notes.
    """
    system = (
        "You are a rigorous reviewer. Output strictly valid JSON. "
        "Compare intended script to spoken transcript and assess alignment."
    )
    user = (
        "[SCRIPT]\n" + script_text +
        "\n[TRANSCRIPT]\n" + transcript_text +
        "\n[INSTRUCTIONS]\nReturn JSON: {\"similarity_0_1\": float, \"notes\": str, \"missing_points\": [str], \"added_points\": [str]}"
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
        return json.loads(txt)
    except Exception:
        return {"similarity_0_1": 0.0, "notes": "", "missing_points": [], "added_points": []}


def review_script_quality(script_text: str) -> Dict[str, Any]:
    """Assess the quality of the provided script (clarity, structure, errors)."""
    system = (
        "You are a senior editor for public speaking scripts. Output strictly valid JSON."
    )
    user = (
        "[SCRIPT]\n" + script_text +
        "\n[INSTRUCTIONS]\nReturn JSON: {\"issues\":[str], \"suggestions\":[str], \"overall\": str}"
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
        return json.loads(txt)
    except Exception:
        return {"issues": [], "suggestions": [], "overall": ""}


def analyze_script_with_meta(script_text: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze the provided script text taking into account user's intent meta
    (goal, audience, format, experience). Returns strictly structured JSON:
    {"score_0_100": int, "recommendations": [{"text": str, "important": 0|1}], "thesis": [str]}
    """
    goal = meta.get("goal") or meta.get("goal_other") or ""
    audience = meta.get("audience") or ""
    fmt = meta.get("format") or ""
    experience = meta.get("experience") or ""
    timing_min = meta.get("timing_min") or ""
    direction = meta.get("direction") or ""
    notes = meta.get("notes") or ""

    system = (
        "You are a senior Russian-speaking editor and public speaking coach. "
        "Evaluate the script with respect to user's context (goal, direction, audience, format, experience, notes). "
        "Return strictly valid JSON only."
    )

    meta_blob = {
        "goal": goal,
        "direction": direction,
        "audience": audience,
        "format": fmt,
        "experience": experience,
        "timing_min": timing_min,
        "notes": notes,
    }
    user = (
        "[META]\n" + json.dumps(meta_blob, ensure_ascii=False) +
        "\n[SCRIPT]\n" + (script_text or "") +
        "\n[INSTRUCTIONS]\n"
        "Assess quality and alignment. Score from 0 to 100 (integer). "
        "Give 5–10 concise recommendations in Russian (short actionable sentences), "
        "and mark each recommendation with importance: 1 = highly important, 0 = important. "
        "Generate 3–7 thesis bullet points in Russian (max 12 words each). "
        "Return JSON: {\"score_0_100\": int, \"recommendations\":[{\"text\": str, \"important\": 0|1}], \"thesis\":[str]}"
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
        # sanitize
        score = parsed.get("score_0_100")
        try:
            score = int(score)
        except Exception:
            score = 0
        score = max(0, min(100, score))

        raw_recs = parsed.get("recommendations") or []
        recs_out: List[Dict[str, Any]] = []
        for item in raw_recs[:10]:
            try:
                text_val = str(item.get("text", "")).strip()
                imp_val = item.get("important", 0)
                try:
                    imp_int = int(imp_val)
                except Exception:
                    imp_int = 0
                imp_int = 1 if imp_int == 1 else 0
                if text_val:
                    recs_out.append({"text": text_val, "important": imp_int})
            except Exception:
                continue

        thesis = [str(x) for x in (parsed.get("thesis") or [])][:10]
        logging.getLogger(__name__).info("analyze_script", extra={"score": score, "recs": len(recs_out), "thesis": len(thesis)})
        return {"score_0_100": score, "recommendations": recs_out, "thesis": thesis}
    except Exception:
        return {"score_0_100": 0, "recommendations": [], "thesis": []}


def generate_objections_with_answers(
    transcript_text: str,
    meta: Dict[str, Any],
    slides: Optional[List[Dict[str, Any]]] = None,
    per_slide_text: Optional[Dict[int, str]] = None,
    deck_metrics: Optional[Dict[str, Any]] = None,
    per_slide_eval: Optional[List[Dict[str, Any]]] = None,
    weak_slides: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Generate role-based questions using ONLY transcript and meta (no slides).

    Returns JSON: {"roles": [{"actor": str, "question": str, "slide": int|null, "quote": str, "options": [{"text": str, "grade": "good|mid|bad", "explanation": str}]}]}
    """
    goal = meta.get("goal") or meta.get("goal_other") or ""
    audience = meta.get("audience") or ""
    fmt = meta.get("format") or ""
    experience = meta.get("experience") or ""
    timing_min = meta.get("timing_min") or ""
    direction = meta.get("direction") or ""
    notes = meta.get("notes") or ""

    system = (
        "You are a Russian-speaking role-play coach for objection handling. "
        "Use the provided transcript to craft SPECIFIC, contextual questions. "
        "For each role, generate ONE concise but challenging question grounded in what the speaker actually said. "
        "Include a short quote/paraphrase from the transcript as evidence. If slides are not provided, set slide to null. "
        "Output strictly valid JSON only."
    )

    meta_blob = {
        "goal": goal,
        "direction": direction,
        "audience": audience,
        "format": fmt,
        "experience": experience,
        "timing_min": timing_min,
        "notes": notes,
    }

    # Prepare transcript excerpt to keep prompt size reasonable
    try:
        words = re.findall(r"\S+", transcript_text or "")
        transcript_short = " ".join(words[:1200])
    except Exception:
        transcript_short = str(transcript_text or "")[:12000]

    payload = {
        "meta": meta_blob,
        "transcript": transcript_short,
    }

    user = (
        "[CONTEXT]\n" + json.dumps(payload, ensure_ascii=False) +
        "\n[TASK]\nReturn three roles relevant to the context (e.g., Инвестор, Техдиректор, Клиент). "
        "For EACH role, generate ONE specific, CHALLENGING question grounded strictly in the transcript, and THREE answer options: "
        "1 correct (grade=good), 1 partially correct (grade=mid), 1 incorrect (grade=bad). "
        "Provide a short supporting quote/paraphrase from the transcript. Set slide to null if unknown. "
        "\n[STRICT FORMAT]\n{\"roles\":[{\"actor\":str, \"question\":str, \"slide\": int|null, \"quote\": str, \"options\":[{\"text\":str, \"grade\":\"good|mid|bad\", \"explanation\":str}]}]}"
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
        roles = parsed.get("roles") or []
        out_roles: List[Dict[str, Any]] = []
        for r in roles:
            actor = str(r.get("actor", ""))
            question = str(r.get("question", ""))
            slide_val = r.get("slide", None)
            try:
                slide_num = int(slide_val) if slide_val is not None else None
            except Exception:
                slide_num = None
            quote = str(r.get("quote", "")).strip()
            opts_raw = r.get("options") or []
            options: List[Dict[str, Any]] = []
            for o in opts_raw[:3]:
                text = str(o.get("text", ""))
                grade = str(o.get("grade", "")).lower()
                explanation = str(o.get("explanation", ""))
                if text and grade in {"good", "mid", "bad"}:
                    options.append({"text": text, "grade": grade, "explanation": explanation})
            if actor and question and options:
                out_roles.append({"actor": actor, "question": question, "slide": slide_num, "quote": quote, "options": options})
        logging.getLogger(__name__).info("objections_generated", extra={"roles": len(out_roles)})
        return {"roles": out_roles[:3]}
    except Exception:
        return {"roles": []}


def review_deck_with_llm(
    slides: List[Dict[str, Any]],
    deck_metrics: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Ask LLM to review slide deck quality and return concise recommendations.

    Returns {"recommendations": [str]}
    """
    meta = meta or {}
    # Compact slide content to keep prompt short
    compact_slides: List[Dict[str, Any]] = []
    for s in slides[:30]:
        title = str(s.get("title", ""))
        bullets = s.get("bullets") or []
        bullets_joined = " \n- ".join([str(b)[:300] for b in bullets][:3])
        compact_slides.append({
            "index": s.get("index"),
            "title": title[:120],
            "bullets": bullets_joined[:600],
        })

    system = (
        "Ты — строгий русскоязычный консультант по дизайну презентаций. "
        "Кратко и по делу укажи, что улучшить: структура, визуал, плотность текста, читаемость, акценты. "
        "Выдай строго валидный JSON."
    )
    payload = {
        "meta": {
            "goal": meta.get("goal") or meta.get("goal_other") or None,
            "direction": meta.get("direction"),
            "format": meta.get("format"),
            "timing_min": meta.get("timing_min"),
            "notes": meta.get("notes"),
        },
        "metrics": deck_metrics,
        "slides": compact_slides,
    }
    user = (
        "[КОНТЕКСТ]\n" + json.dumps(payload, ensure_ascii=False) +
        "\n[ЗАДАНИЕ]\nСформулируй 7–12 конкретных рекомендаций по улучшению слайдов (одно предложение на пункт).\n"
        "Не повторяйся. Учитывай контекст и метрики (плотность/контраст/шрифты/стилистика).\n"
        "[ФОРМАТ ОТВЕТА]\n{\"recommendations\":[str]}"
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
        recs = [str(x) for x in (parsed.get("recommendations") or [])][:12]
    except Exception:
        recs = []
    logging.getLogger(__name__).info("deck_review", extra={"recs": len(recs)})
    return {"recommendations": recs}


def review_deck_per_slide(
    slides: List[Dict[str, Any]],
    deck_metrics: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
    max_slides: int = 30,
) -> Dict[str, Any]:
    """LLM review per slide: returns recommendations per slide and general deck tips.

    Output: {"per_slide":[{"index":int, "recommendations":[str]}], "general":[str]}
    """
    meta = meta or {}
    compact: List[Dict[str, Any]] = []
    for s in slides[:max_slides]:
        title = str(s.get("title", ""))
        bullets = s.get("bullets") or []
        text_joined = " \n- ".join([str(b)[:300] for b in bullets][:4])
        compact.append({"index": s.get("index"), "title": title[:160], "content": text_joined[:800]})

    system = (
        "Ты — строгий русскоязычный консультант по слайдам. Для КАЖДОГО слайда оцени необходимость улучшений и дай до 3–5 кратких рекомендаций (по визуалу/структуре/тексту/акцентам). "
        "Если слайд уже хороший и улучшения не требуются — верни ПУСТОЙ список рекомендаций для этого слайда. Не дублируй одни и те же советы на соседних слайдах. Верни строго JSON."
    )
    payload = {
        "meta": {
            "goal": meta.get("goal") or meta.get("goal_other") or None,
            "direction": meta.get("direction"),
            "format": meta.get("format"),
            "timing_min": meta.get("timing_min"),
            "notes": meta.get("notes"),
        },
        "metrics": deck_metrics,
        "slides": compact,
    }
    user = (
        "[КОНТЕКСТ]\n" + json.dumps(payload, ensure_ascii=False) +
        "\n[ЗАДАНИЕ]\nДля каждого слайда верни ДО 3–5 пунктов, но если улучшения не требуются — верни пустой список. Затем добавь до 5 общих советов по всей колоде.\n"
        "[ФОРМАТ]\n{\"per_slide\":[{\"index\":int, \"recommendations\":[str]}], \"general\":[str]}"
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
        per_slide = parsed.get("per_slide") or []
        general = parsed.get("general") or []
        # sanitize
        out = []
        for item in per_slide:
            try:
                idx = int(item.get("index"))
            except Exception:
                continue
            recs = [str(x) for x in (item.get("recommendations") or [])][:6]
            out.append({"index": idx, "recommendations": recs})
        general_s = [str(x) for x in general][:10]
    except Exception:
        out = []
        general_s = []
    logging.getLogger(__name__).info("deck_review_per_slide", extra={"slides": len(out), "general": len(general_s)})
    return {"per_slide": out, "general": general_s}