from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from email_article_analyzer.investment_scoring import CATEGORY_WEIGHTS
from email_article_analyzer.sector_scoring import SECTOR_WEIGHTS


def recommended_scoring_config() -> dict[str, Any]:
    return {
        "generic": deepcopy(CATEGORY_WEIGHTS),
        "sectors": deepcopy(SECTOR_WEIGHTS),
    }


def validate_scoring_config(payload: dict[str, Any]) -> dict[str, Any]:
    recommended = recommended_scoring_config()
    if not isinstance(payload, dict):
        raise ValueError("Scoring configuration must be an object")
    generic = _validate_model("Generic", payload.get("generic"), recommended["generic"])
    sectors_payload = payload.get("sectors")
    if not isinstance(sectors_payload, dict):
        raise ValueError("Sector weights must be an object")
    if set(sectors_payload) != set(recommended["sectors"]):
        raise ValueError("Sector weights must include exactly the supported research sectors")
    sectors = {
        sector: _validate_model(sector, sectors_payload[sector], defaults)
        for sector, defaults in recommended["sectors"].items()
    }
    return {"generic": generic, "sectors": sectors}


def load_scoring_config(path: Path) -> dict[str, Any]:
    recommended = recommended_scoring_config()
    if not path.exists():
        return recommended
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return validate_scoring_config(payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return recommended


def save_scoring_config(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    validated = validate_scoring_config(payload)
    stored = {
        **validated,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    temporary.replace(path)
    return validated


def reset_scoring_config(path: Path) -> dict[str, Any]:
    if path.exists():
        path.unlink()
    return recommended_scoring_config()


def is_custom_scoring_config(config: dict[str, Any]) -> bool:
    return config != recommended_scoring_config()


def _validate_model(
    label: str,
    weights: Any,
    recommended_weights: dict[str, float],
) -> dict[str, float]:
    if not isinstance(weights, dict) or set(weights) != set(recommended_weights):
        raise ValueError(f"{label} must include exactly the supported criteria")
    validated: dict[str, float] = {}
    for criterion in recommended_weights:
        value = weights[criterion]
        if isinstance(value, bool):
            raise ValueError(f"{label} {criterion} weight must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} {criterion} weight must be numeric") from exc
        if not math.isfinite(number) or number < 0 or number > 100:
            raise ValueError(f"{label} {criterion} weight must be between 0 and 100")
        validated[criterion] = round(number, 4)
    if not math.isclose(sum(validated.values()), 100.0, abs_tol=0.001):
        raise ValueError(f"{label} weights must total 100%")
    return validated
