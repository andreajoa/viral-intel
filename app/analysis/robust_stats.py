"""Robust statistics for profile-relative content intelligence.

Social metrics are heavy-tailed: a single breakout post can move a mean dramatically.
Viral Intel therefore models comparable posts in log space and uses median/MAD-based
intervals. The output is descriptive and uncertainty-aware; it is not a claim about a
platform's private ranking model.
"""

from __future__ import annotations

import math
from statistics import median


def percentile(values: list[float], target: float) -> float:
    if not values:
        return 0.0
    below = sum(value < target for value in values)
    equal = sum(value == target for value in values)
    return round(((below + 0.5 * equal) / len(values)) * 100, 1)


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def robust_expected_range(values: list[float], target: float) -> dict[str, float | str | None]:
    """Return a robust expected interval and standardized anomaly score.

    Counts are transformed with log1p to reduce the leverage of very large viral
    observations. MAD is preferred; IQR and a small scale floor keep the model stable
    when a profile is unusually consistent.
    """

    clean = [float(value) for value in values if value is not None and float(value) >= 0]
    if len(clean) < 5:
        return {
            "expected_low": None,
            "expected_high": None,
            "robust_z_score": None,
            "dispersion_pct": None,
            "evidence_strength": "NÃO_AVALIÁVEL",
        }

    logs = [math.log1p(value) for value in clean]
    center = float(median(logs))
    deviations = [abs(value - center) for value in logs]
    mad = float(median(deviations))
    robust_sigma = 1.4826 * mad

    if robust_sigma < 0.025:
        q1 = _quantile(logs, 0.25)
        q3 = _quantile(logs, 0.75)
        iqr_sigma = (q3 - q1) / 1.349 if q3 > q1 else 0.0
        robust_sigma = max(iqr_sigma, 0.05)

    # About a 95% descriptive envelope under a roughly symmetric log distribution.
    low = max(0.0, math.expm1(center - 2.0 * robust_sigma))
    high = max(low, math.expm1(center + 2.0 * robust_sigma))
    target_log = math.log1p(max(0.0, float(target)))
    z_score = (target_log - center) / robust_sigma if robust_sigma else 0.0
    center_raw = max(0.0, math.expm1(center))
    dispersion = ((high - low) / max(center_raw, 1.0)) * 100

    count = len(clean)
    evidence_strength = "FORTE" if count >= 15 else "MODERADA" if count >= 8 else "FRACA"
    return {
        "expected_low": round(low, 4),
        "expected_high": round(high, 4),
        "robust_z_score": round(z_score, 3),
        "dispersion_pct": round(dispersion, 2),
        "evidence_strength": evidence_strength,
    }
