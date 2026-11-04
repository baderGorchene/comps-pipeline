"""AI Model Router: dual-provider hot failover execution (v3.6 specification).

Primary: OpenAI gpt-6.1-terra
Fallback: Google gemini-flash-latest
Heuristic Fallback: zero-downtime offline rule-based parser
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from comps_pipeline.ai.parsers import (
    CompRejectionJustification,
    LeaseAnalysisResult,
    OwnerClassificationResult,
)
from comps_pipeline.ai.prompts import (
    LEASE_DETECTION_SYSTEM,
    OWNER_CLASSIFICATION_SYSTEM,
    REJECTION_JUSTIFICATION_SYSTEM,
)

log = logging.getLogger(__name__)

PRIMARY_MODEL = "gpt-6.1-terra"
FALLBACK_MODEL = "gemini-flash-latest"


def _load_env_keys() -> tuple[str, str]:
    """Load OpenAI and Gemini keys from environment or .env file."""
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if not openai_key or not gemini_key:
        env_path = Path(".env")
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("\"'")
                    if k == "OPENAI_API_KEY" and not openai_key and v and v != "YOUR_API_KEY":
                        openai_key = v
                    elif k == "GEMINI_API_KEY" and not gemini_key and v and v != "YOUR_API_KEY":
                        gemini_key = v
            except Exception as e:
                log.debug("Error reading .env: %s", e)

    return openai_key, gemini_key


def _clean_json_text(text: str) -> str:
    """Extract clean JSON from model output that may include markdown code fences."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text


class AIModelRouter:
    """Fault-tolerant dual-provider model router with instant failover."""

    def __init__(
        self,
        primary_model: str = PRIMARY_MODEL,
        fallback_model: str = FALLBACK_MODEL,
        timeout: float = 8.0,
    ) -> None:
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.timeout = timeout
        self.openai_key, self.gemini_key = _load_env_keys()
        self._executor = ThreadPoolExecutor(max_workers=4)

    def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        if not self.openai_key or self.openai_key == "YOUR_API_KEY":
            raise ValueError("OPENAI_API_KEY is not set or invalid.")

        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": self.primary_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openai_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        if not self.gemini_key or self.gemini_key == "YOUR_API_KEY":
            raise ValueError("GEMINI_API_KEY is not set or invalid.")

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.fallback_model}:generateContent?key={self.gemini_key}"
        )
        combined = f"{system_prompt}\n\nUser Request:\n{user_prompt}\n\nRespond with valid JSON only."
        payload = {
            "contents": [{"parts": [{"text": combined}]}],
            "generationConfig": {"temperature": 0.2},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"]

    def execute(self, system_prompt: str, user_prompt: str) -> tuple[str, str]:
        """Execute request with hot failover: Primary -> Fallback -> Heuristic string.

        Returns (response_text, model_identifier_used).
        """
        # Fast path during test runs or if explicitly disabled
        if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("DISABLE_AI_NETWORK") == "1":
            return "", "heuristic_fallback"

        # 1. Try Primary
        try:
            raw = self._call_openai(system_prompt, user_prompt)
            return raw, self.primary_model
        except Exception as e:
            log.warning(
                "[AI_ROUTER_FALLBACK_TRIGGERED: %s -> %s] Primary call failed: %s",
                self.primary_model,
                self.fallback_model,
                e,
            )

        # 2. Try Fallback
        try:
            raw = self._call_gemini(system_prompt, user_prompt)
            return raw, self.fallback_model
        except Exception as e:
            log.warning(
                "Fallback call %s also failed or was unconfigured: %s",
                self.fallback_model,
                e,
            )

        return "", "heuristic_fallback"

    def classify_owner(self, owner_name: str) -> tuple[OwnerClassificationResult, str]:
        """Classify owner into BUILDER vs INDIVIDUAL with LLM, falling back to heuristics."""
        name = (owner_name or "").strip()
        if not name:
            return OwnerClassificationResult(owner_type="INDIVIDUAL", confidence=1.0, reasoning="Blank owner"), "heuristic_fallback"

        # Heuristic rules:
        builder_indicators = (
            "llc", "inc", "corp", "corporation", "ltd", "builders", "builder",
            "construction", "homes", "properties", "development", "enterprises",
            "holding", "dr horton", "lennar", "kb home", "pulte", "beazer", "ammo"
        )
        norm = name.casefold()
        heuristic_builder = any(ind in norm for ind in builder_indicators)

        raw, model = self.execute(
            OWNER_CLASSIFICATION_SYSTEM,
            f"Classify this owner name: '{name}'"
        )
        if raw:
            try:
                data = json.loads(_clean_json_text(raw))
                res = OwnerClassificationResult.model_validate(data)
                return res, model
            except Exception as e:
                log.debug("JSON parse failed for owner classification: %s", e)

        # Fallback heuristic result
        owner_type = "BUILDER" if heuristic_builder else "INDIVIDUAL"
        return OwnerClassificationResult(
            owner_type=owner_type,
            confidence=0.9 if heuristic_builder else 0.7,
            reasoning=f"Matched entity keywords in '{name}'" if heuristic_builder else "Standard individual name",
        ), "heuristic_fallback"

    def detect_lease(self, remarks: str) -> tuple[LeaseAnalysisResult, str]:
        """Detect lease, tenant, or rental indicators in remarks text."""
        text = (remarks or "").strip()
        if not text:
            return LeaseAnalysisResult(has_lease_indicator=False, confidence=1.0), "heuristic_fallback"

        # Heuristic keywords from specification:
        patterns = (
            r"\bleased\b",
            r"\btenant occupied\b",
            r"\binvestment property\b",
            r"\bshort term rental\b",
            r"\bstr\b",
            r"\blease in place\b",
            r"\bpaying \$\d+",
            r"\btenant rights\b",
            r"\bcurrent rent\b",
        )
        found = [p for p in patterns if re.search(p, text, re.IGNORECASE)]

        raw, model = self.execute(
            LEASE_DETECTION_SYSTEM,
            f"Analyze remarks for tenant/lease indicators:\n\n{text}"
        )
        if raw:
            try:
                data = json.loads(_clean_json_text(raw))
                res = LeaseAnalysisResult.model_validate(data)
                return res, model
            except Exception as e:
                log.debug("JSON parse failed for lease detection: %s", e)

        return LeaseAnalysisResult(
            has_lease_indicator=bool(found),
            lease_phrases=found,
            confidence=0.9 if found else 0.8,
            summary="Tenant or lease terms detected in remarks" if found else "No rental terms found",
        ), "heuristic_fallback"

    def generate_rejection_justification(
        self,
        candidate: Any,
        subject: Any,
        final_picks: list[Any],
    ) -> tuple[str, str]:
        """Generate a 1 to 2 sentence justification for why a shortlisted comp was bypassed."""
        # Calculate comparison deltas
        c_dist = candidate.distance_miles.value
        c_gla = candidate.living_area.value
        c_price = candidate.close_price.value or candidate.list_price.value
        tier = candidate.subdivision_tier.value
        is_leased = bool(candidate.remarks_signals.get("_is_leased"))

        subj_gla = subject.living_area
        gla_diff_pct = candidate.gla_diff_pct.value

        user_prompt = (
            f"Candidate Property (MLS #{candidate.mls_number}):\n"
            f"- Distance: {c_dist:.2f} mi from subject\n"
            f"- Living Area: {c_gla} sq ft ({gla_diff_pct:+.1f}% vs subject {subj_gla} sq ft)\n"
            f"- Price: ${c_price:,} (Pool: {candidate.pool})\n"
            f"- Subdivision Tier: {tier} (Raw: {candidate.subdivision_raw.value})\n"
            f"- Lease Status: {'Tenant Occupied / Leased (C2)' if is_leased else 'Owner/Builder Occupied'}\n\n"
            f"Subject Property:\n"
            f"- Address: {subject.address}\n"
            f"- Living Area: {subj_gla} sq ft | Subdivision: {subject.subdivision}\n\n"
            f"Final Selected Comps:\n"
        )
        for i, p in enumerate(final_picks, 1):
            user_prompt += (
                f"  Comp {i} (MLS #{p.mls_number}): {p.living_area.value} sq ft, "
                f"{p.distance_miles.value:.2f} mi, ${p.close_price.value or p.list_price.value:,}\n"
            )

        raw, model = self.execute(REJECTION_JUSTIFICATION_SYSTEM, user_prompt)
        if raw:
            try:
                data = json.loads(_clean_json_text(raw))
                parsed = CompRejectionJustification.model_validate(
                    {"mls_number": candidate.mls_number, **data}
                )
                if parsed.justification:
                    return parsed.justification, model
            except Exception as e:
                log.debug("JSON parse failed for rejection justification: %s", e)

        # High-precision deterministic appraisal heuristic fallback
        reasons = []
        if c_dist is not None and c_dist > 0.5:
            reasons.append(f"farther proximity ({c_dist:.2f} mi away)")
        if gla_diff_pct is not None and abs(gla_diff_pct) > 10:
            reasons.append(f"larger living area divergence ({gla_diff_pct:+.1f}%)")
        if tier is not None and tier > 1:
            reasons.append("competing location outside the subject's immediate subdivision")
        if is_leased:
            reasons.append("active lease history noted in remarks indicating tenant occupancy")

        if not reasons:
            reasons.append("lower overall ranking priority against closer bracketed alternatives")

        justification = (
            f"Bypassed in favor of higher-ranked primary comps due to "
            f"{', and '.join(reasons[:2])}."
        )
        return justification, "heuristic_fallback"

    def submit_rejections_async(
        self,
        candidates: list[Any],
        subject: Any,
        final_picks: list[Any],
    ) -> Future:
        """Asynchronously compute all rejection justifications on a background thread."""
        def _task():
            results = {}
            model_used = self.primary_model
            for c in candidates:
                text, model = self.generate_rejection_justification(c, subject, final_picks)
                results[c.mls_number] = text
                if model != "heuristic_fallback":
                    model_used = model
            return results, model_used

        return self._executor.submit(_task)
