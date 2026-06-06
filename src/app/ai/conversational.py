"""Conversational query helper for admin-facing dashboard questions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import app.config as config
from app.database.models import ScanJob
from app.database.repository import AlertRepository
from app.services.wishlist import WishlistService
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ConversationalAnswer:
    """Structured response from the conversational query helper."""

    question: str
    answer: str
    sources: list[str]
    model: str | None = None
    used_openai: bool = False


def _collect_context(session) -> dict[str, Any]:
    entries = WishlistService.get_all(session)
    active_entries = [entry for entry in entries if entry.is_active]
    alerts = AlertRepository.get_unnotified(session, limit=25)
    recent_scans = (
        session.query(ScanJob)
        .order_by(ScanJob.started_at.desc())
        .limit(5)
        .all()
    )

    return {
        "counts": {
            "wishlist_entries": len(entries),
            "active_wishlist_entries": len(active_entries),
            "pending_alerts": len(alerts),
        },
        "recent_wishlist": [
            {
                "id": entry.id,
                "title": entry.title,
                "platform": entry.platform,
                "brand": entry.brand,
                "model_name": entry.model_name,
                "normalized_name": entry.normalized_name,
                "is_active": entry.is_active,
                "source_url": entry.source_url,
                "notes": entry.notes,
            }
            for entry in entries[:10]
        ],
        "recent_scans": [
            {
                "scan_type": scan.scan_type,
                "status": scan.status,
                "products_found": scan.products_found,
                "products_updated": scan.products_updated,
                "completed_at": str(scan.completed_at) if scan.completed_at is not None else None,
            }
            for scan in recent_scans
        ],
        "pending_alerts": [
            {
                "id": alert.id,
                "type": alert.alert_type,
                "message": alert.message,
                "product_id": alert.product_id,
            }
            for alert in alerts
        ],
    }


def _build_system_prompt() -> str:
    return (
        "You are the admin assistant for a sneaker price tracker dashboard. "
        "Answer only using the supplied data context. "
        "If the answer is not present, say that the current data does not show it. "
        "Be concise, factual, and helpful. "
        "When relevant, reference counts, URLs, product titles, or scan status. "
        "Do not invent products, alerts, or scan results."
    )


def _render_local_answer(question: str, context: dict[str, Any]) -> str:
    lowered = question.lower()
    counts = context["counts"]

    if "how many" in lowered or "count" in lowered:
        return (
            f"Wishlist entries: {counts['wishlist_entries']}. "
            f"Active entries: {counts['active_wishlist_entries']}. "
            f"Pending alerts: {counts['pending_alerts']}."
        )

    if "recent scan" in lowered or "last scan" in lowered or "scan" in lowered:
        if not context["recent_scans"]:
            return "I do not see any scan history yet."
        latest = context["recent_scans"][0]
        return (
            f"Latest scan: {latest['scan_type']} is {latest['status']} "
            f"with {latest['products_found']} products found and {latest['products_updated']} updated."
        )

    if "alert" in lowered:
        if not context["pending_alerts"]:
            return "There are no pending alerts right now."
        sample = context["pending_alerts"][0]
        return (
            f"There are {counts['pending_alerts']} pending alerts. "
            f"Example: {sample['type']} for product {sample['product_id']}."
        )

    if "wishlist" in lowered or "alert" in lowered or "product" in lowered:
        if not context["recent_wishlist"]:
            return "There are no wishlist entries yet."
        sample = context["recent_wishlist"][0]
        return (
            f"Latest wishlist item: {sample['title']} on {sample['platform']} "
            f"({sample['source_url']})."
        )

    return (
        "I can summarize wishlist counts, scan activity, and pending alerts from the current data. "
        "Ask about totals, the latest scan, or a specific product."
    )


def answer_question(session, question: str) -> ConversationalAnswer:
    """Answer an admin question using local data plus optional OpenAI help."""
    cleaned_question = question.strip()
    if not cleaned_question:
        raise ValueError("question is required")

    context = _collect_context(session)
    sources = ["dashboard database", "wishlist entries", "scan jobs", "alerts"]

    if not config.settings.openai_api_key:
        return ConversationalAnswer(
            question=cleaned_question,
            answer=_render_local_answer(cleaned_question, context),
            sources=sources,
            model=None,
            used_openai=False,
        )

    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - dependency issue
        logger.warning("openai_unavailable", error=str(exc))
        return ConversationalAnswer(
            question=cleaned_question,
            answer=_render_local_answer(cleaned_question, context),
            sources=sources,
            model=None,
            used_openai=False,
        )

    client = OpenAI(api_key=config.settings.openai_api_key)
    model_name = config.settings.openai_model_main
    try:
        response = client.responses.create(
            model=model_name,
            input=[
                {
                    "role": "system",
                    "content": _build_system_prompt(),
                },
                {
                    "role": "user",
                    "content": (
                        "Question:\n"
                        f"{cleaned_question}\n\n"
                        "Data context:\n"
                        f"{json.dumps(context, ensure_ascii=False)}"
                    ),
                },
            ],
        )
        answer_text = getattr(response, "output_text", None)
    except Exception as exc:  # pragma: no cover - external API failure
        logger.warning("openai_query_failed", error=str(exc))
        answer_text = None

    used_openai = answer_text is not None
    if not answer_text:
        answer_text = _render_local_answer(cleaned_question, context)

    return ConversationalAnswer(
        question=cleaned_question,
        answer=answer_text.strip(),
        sources=sources,
        model=model_name,
        used_openai=used_openai,
    )
