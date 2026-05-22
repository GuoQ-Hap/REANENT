from __future__ import annotations

import re

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.domain import TaskRequest
from pmc_agent.model import IntentAssessment, IntentModelClient


MATERIAL_PATTERNS = [
    re.compile(r"(?<![A-Z0-9])B0[A-Z0-9]{8}(?![A-Z0-9])", re.IGNORECASE),
    re.compile(r"(?<![A-Z0-9])[A-Z]{1,4}\d{2,6}(?![A-Z0-9])", re.IGNORECASE),
]
logger = get_logger(__name__)


def enrich_request(text: str) -> TaskRequest:
    material_code = _extract_material_code(text)
    logger.debug(
        "request enriched",
        extra=log_extra("request_enriched", material_code=material_code or "-"),
    )
    return TaskRequest(text=text, material_code=material_code)


def _extract_material_code(text: str) -> str | None:
    for pattern in MATERIAL_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0).upper()
    return None


def classify_task(
    request: TaskRequest,
    intent_model: IntentModelClient,
    recent_context: list[dict] | None = None,
) -> IntentAssessment:
    assessment = intent_model.assess_intent(request, recent_context=recent_context)
    logger.info(
        "intent assessed",
        extra=log_extra(
            "intent_assessed",
            task_type=assessment.task_type.value,
            confidence=assessment.confidence,
            risk_level=assessment.risk_level,
        ),
    )
    if assessment.confidence < 0.6:
        logger.warning(
            "low confidence intent assessment",
            extra=log_extra("intent_low_confidence", task_type=assessment.task_type.value, confidence=assessment.confidence),
        )
    return assessment
