"""
Profile-aware sponsor score engine.

Supports two modes:
1) Rule-based profile scoring (preferred when profile has scoring_rules)
2) Legacy weighted fallback (when no profile rules are active)
"""

import re
from typing import Any

# ---------------------------------------------------------------------------
# Legacy fallback weights (used only when no profile rules are active)
# ---------------------------------------------------------------------------
INDUSTRY_RELEVANCE = {
    # Top tier — directly car related
    "Auto Parts":         25,
    "Automotive Shop":    25,
    "Auto Detailing":     25,
    "Tire Shop":          23,
    "Car Wash":           20,
    "Car Dealership":     18,
    "Motorcycle Shop":    17,
    "Go-Kart Track":      15,
    "Gas Station":        15,
    "Vehicle Inspection": 13,
    "Car Rental":         12,

    # Medium tier — good fit for young-adult/enthusiast crowd
    "Brewery":            12,
    "Bar":                10,
    "Nightclub":          10,
    "Sporting Goods":      8,
    "Outdoor/Sports Store": 8,
    "Gym":                 7,
    "Sports":              7,
    "Tattoo Parlor":       8,
    "Barber":              7,
    "Electronics":         7,
    "Arcade":              7,
    "Bowling Alley":       5,

    # Lower tier — general
    "Restaurant":          4,
    "Fast Food":           2,
    "Cafe":                4,
    "Hotel":               5,
    "Clothing Store":      3,
}

DEFAULT_RELEVANCE = 1  # anything not in the map

# ---------------------------------------------------------------------------
# Legacy audience overlap scores (fallback mode)
# ---------------------------------------------------------------------------
HIGH_OVERLAP_AUDIENCES = {
    "Car enthusiasts, vehicle owners",
    "Car enthusiasts, DIY mechanics",
    "Car enthusiasts, detailing hobbyists",
    "Car buyers, vehicle enthusiasts",
    "Motorcycle enthusiasts, riders",
    "Car enthusiasts, young adults 16–35",
}
MEDIUM_OVERLAP_AUDIENCES = {
    "Young adults 18–35, professionals",
    "Young adults 16–35, fashion-conscious",
    "Young men 16–40",
    "Adults 21+, nightlife crowd",
    "Young adults 21–30, nightlife crowd",
    "Craft beer enthusiasts, adults 21+",
    "Young adults 18–35, counter-culture crowd",
    "Tech-savvy young adults 18–35",
    "Athletes, active young adults",
    "Fitness-focused adults 18–45",
    "Young adults 16–30, gamers",
}

# Social media tag keys to check in OSM tags
_SOCIAL_MEDIA_KEYS = {
    "contact:facebook", "facebook",
    "contact:instagram", "instagram",
    "contact:twitter", "twitter",
    "contact:youtube", "youtube",
    "contact:tiktok", "tiktok",
}

# Contact/info fields used for data-completeness scoring
_COMPLETENESS_KEYS = (
    "name", "phone", "contact:phone",
    "website", "contact:website",
    "opening_hours",
    "addr:housenumber", "addr:street",
    "addr:city",
    "contact:email", "email",
)

FIELD_ALIASES = {
    "distance_mi": "distance_miles",
    "audience_overlap": "target_audience",
}

PROFILE_TEXT_FIELDS = (
    "name",
    "industry",
    "category",
    "target_audience",
    "audience_overlap",
    "parent_company",
    "website",
)

SPECIFIC_RULE_FIELDS = {
    "industry",
    "category",
    "audience_overlap",
    "target_audience",
    "entity_type",
    "parent_company",
}

GENERIC_RULE_FIELDS = {
    "is_chain",
    "has_website",
    "has_email",
    "has_phone",
    "has_opening_hours",
    "osm_completeness",
    "distance_mi",
    "distance_miles",
    "num_locations",
    "chain_confidence",
    "founded_year",
}

INDUSTRY_EQUIVALENTS = {
    "auto detailing": {
        "detailing",
        "car detailing",
        "auto detail",
        "detail shop",
    },
    "automotive shop": {
        "auto repair",
        "car repair",
        "mechanic",
        "repair shop",
    },
    "performance shop": {
        "performance",
        "tuning",
        "speed shop",
        "dyno",
    },
    "auto wrap shop": {
        "wrap",
        "vehicle wrap",
        "vinyl wrap",
    },
    "sign shop": {
        "sign",
        "signage",
        "graphics",
        "print shop",
    },
    "watch store": {
        "watch",
        "watches",
        "timepiece",
    },
}


# ---------------------------------------------------------------------------
# Individual factor scorers
# ---------------------------------------------------------------------------

def _industry_score(industry: str) -> int:
    return INDUSTRY_RELEVANCE.get(industry, DEFAULT_RELEVANCE)


def _chain_score(is_chain: bool) -> int:
    return 0 if is_chain else 15


def _website_score(website: str) -> int:
    return 8 if website else 0


def _phone_score(phone: str) -> int:
    return 8 if phone else 0


def _distance_score(distance_miles: float, max_radius: float = 25.0) -> int:
    """Inverse linear: 12 pts at 0 mi, 0 pts at max_radius."""
    if distance_miles is None or distance_miles < 0:
        return 0
    if distance_miles >= max_radius:
        return 0
    score = 12 * (1.0 - distance_miles / max_radius)
    return round(score)


def _audience_score(target_audience: str) -> int:
    if target_audience in HIGH_OVERLAP_AUDIENCES:
        return 12
    if target_audience in MEDIUM_OVERLAP_AUDIENCES:
        return 6
    return 1


def _opening_hours_score(tags: dict) -> int:
    """5 pts if opening_hours is listed — signals business is properly documented."""
    return 5 if tags.get("opening_hours", "").strip() else 0


def _social_media_score(tags: dict) -> int:
    """5 pts if any social media presence is found in OSM tags."""
    for key in _SOCIAL_MEDIA_KEYS:
        if tags.get(key, "").strip():
            return 5
    return 0


def _data_completeness_score(tags: dict, business: dict) -> int:
    """
    Up to 5 pts based on how many contact/info fields are filled.
    5 pts → 6+ fields, 3 pts → 3–5 fields, 1 pt → 1–2 fields, 0 → none.
    """
    filled = 0
    for key in _COMPLETENESS_KEYS:
        val = tags.get(key, "") or business.get(key.replace("contact:", ""), "") or ""
        if str(val).strip():
            filled += 1
    if filled >= 6:
        return 5
    if filled >= 3:
        return 3
    if filled >= 1:
        return 1
    return 0


def _email_score(tags: dict) -> int:
    """5 pts if an email contact is found — indicates a business is reachable."""
    for key in ("contact:email", "email"):
        if tags.get(key, "").strip():
            return 5
    return 0


def _normalize_text(value: Any) -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def _normalized_tokens(value: Any) -> set[str]:
    return set(_normalize_text(value).split())


def _get_business_value(business: dict, field: str) -> Any:
    tags = business.get("tags", {})

    if field in FIELD_ALIASES:
        field = FIELD_ALIASES[field]

    if field == "distance_miles":
        return business.get("distance_miles", business.get("distance_mi", 0.0))
    if field == "target_audience":
        return business.get("target_audience", business.get("audience_overlap", ""))

    if field == "has_website":
        return bool(tags.get("website") or tags.get("contact:website") or business.get("website"))
    if field == "has_phone":
        return bool(tags.get("phone") or tags.get("contact:phone") or business.get("phone"))
    if field == "has_email":
        return bool(tags.get("email") or tags.get("contact:email") or business.get("email"))
    if field == "has_opening_hours":
        return bool(tags.get("opening_hours") or business.get("opening_hours"))
    if field == "osm_completeness":
        return _compute_osm_completeness(tags, business)
    if field == "chain_confidence":
        if "chain_confidence" in business:
            return business.get("chain_confidence")
        return 80 if business.get("is_chain") else 0
    if field == "audience_overlap":
        return business.get("target_audience", "")
    return business.get(field)


def _compute_osm_completeness(tags: dict, business: dict) -> int:
    required = (
        "name",
        "phone",
        "email",
        "website",
        "opening_hours",
        "addr:street",
        "addr:city",
    )
    present = 0
    for key in required:
        if key in ("phone", "email", "website"):
            val = (
                tags.get(key)
                or tags.get(f"contact:{key}")
                or business.get(key, "")
            )
        else:
            val = tags.get(key) or business.get(key, "")
        if str(val).strip():
            present += 1
    return round((present / len(required)) * 100)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "y")


def _industry_match(actual: Any, expected: Any) -> bool:
    actual_norm = _normalize_text(actual)
    expected_norm = _normalize_text(expected)
    if not actual_norm or not expected_norm:
        return actual_norm == expected_norm

    if actual_norm == expected_norm:
        return True

    aliases = set(INDUSTRY_EQUIVALENTS.get(expected_norm, set()))
    aliases.add(expected_norm)
    if actual_norm in aliases:
        return True

    actual_tokens = _normalized_tokens(actual_norm)
    expected_tokens = _normalized_tokens(expected_norm)
    return bool(expected_tokens) and expected_tokens.issubset(actual_tokens)


def evaluate_rule(field_name: str, field_value: Any, operator: str, rule_value: Any) -> bool:
    if operator == "is empty":
        return field_value in (None, "", [], {})
    if operator == "is not empty":
        return field_value not in (None, "", [], {})

    if field_value is None:
        return False

    if isinstance(field_value, bool) or isinstance(rule_value, bool):
        left = _coerce_bool(field_value)
        right = _coerce_bool(rule_value)
        if operator == "=":
            return left == right
        if operator == "!=":
            return left != right
        return False

    if field_name in ("industry", "category") and operator in ("=", "!="):
        match = _industry_match(field_value, rule_value)
        return match if operator == "=" else not match

    ops = {
        "=": lambda a, b: str(a).lower() == str(b).lower(),
        "!=": lambda a, b: str(a).lower() != str(b).lower(),
        ">": lambda a, b: float(a) > float(b),
        "<": lambda a, b: float(a) < float(b),
        ">=": lambda a, b: float(a) >= float(b),
        "<=": lambda a, b: float(a) <= float(b),
        "contains": lambda a, b: str(b).lower() in str(a).lower(),
        "not contains": lambda a, b: str(b).lower() not in str(a).lower(),
    }
    try:
        return ops[operator](field_value, rule_value)
    except Exception:
        return False


def _profile_priority_keywords(profile: dict, rules: list[dict]) -> list[str]:
    keywords: list[str] = []

    for rule in rules:
        field = str(rule.get("field", ""))
        operator = str(rule.get("operator", ""))
        value = rule.get("value", "")
        points = int(rule.get("points", 0) or 0)
        if points <= 0:
            continue
        if field not in ("industry", "category", "audience_overlap"):
            continue
        if operator not in ("=", "contains"):
            continue

        text = _normalize_text(value)
        if text:
            keywords.append(text)

    for kw in profile.get("priority_keywords", []):
        text = _normalize_text(kw)
        if text:
            keywords.append(text)

    for kw in profile.get("audience_keywords", []):
        text = _normalize_text(kw)
        if text:
            keywords.append(text)

    seen = set()
    deduped = []
    for kw in keywords:
        if kw not in seen:
            deduped.append(kw)
            seen.add(kw)
    return deduped


def _profile_priority_bonus(business: dict, profile: dict, rules: list[dict]) -> int:
    keywords = _profile_priority_keywords(profile, rules)
    if not keywords:
        return 0

    tags = business.get("tags", {})
    text_parts = [str(business.get(field, "")) for field in PROFILE_TEXT_FIELDS]
    text_parts.extend(
        str(tags.get(k, ""))
        for k in ("shop", "amenity", "office", "leisure", "description", "cuisine")
    )
    haystack = _normalize_text(" ".join(text_parts))
    if not haystack:
        return 0

    matched = 0
    for kw in keywords:
        if kw in haystack:
            matched += 1

    bonus = matched * 2
    max_bonus = int(profile.get("priority_bonus_cap", 16) or 16)
    return min(max_bonus, bonus)


def _compute_rule_based_score(business: dict, rules: list[dict], profile: dict | None = None) -> int:
    score = 0
    matched_rules: list[dict] = []
    relevance_matched = False

    distance_candidates: list[int] = []

    require_relevance = bool(profile.get("require_relevance_for_generic")) if profile else False
    fallback_scale = float(profile.get("generic_scale_without_relevance", 1.0)) if profile else 1.0

    for rule in rules:
        field = str(rule.get("field", "")).strip()
        operator = str(rule.get("operator", "")).strip()
        value = rule.get("value")
        points = int(rule.get("points", 0) or 0)

        if not field or not operator or points <= 0:
            continue

        field_value = _get_business_value(business, field)
        if evaluate_rule(field, field_value, operator, value):
            is_specific = field in SPECIFIC_RULE_FIELDS
            is_generic = field in GENERIC_RULE_FIELDS
            if is_specific:
                relevance_matched = True

            awarded = points
            scaled = False
            if require_relevance and is_generic and not relevance_matched:
                awarded = max(1, round(points * fallback_scale))
                scaled = awarded != points

            if field in ("distance_mi", "distance_miles"):
                distance_candidates.append(awarded)
                matched_rules.append({
                    "label": f"{field} {operator} {value}",
                    "awarded": awarded,
                    "base": points,
                    "scaled": scaled,
                })
            else:
                score += awarded
                matched_rules.append({
                    "label": f"{field} {operator} {value}",
                    "awarded": awarded,
                    "base": points,
                    "scaled": scaled,
                })

    if distance_candidates:
        awarded = max(distance_candidates)
        score += awarded
        matched_rules.append({"label": "distance tier", "awarded": awarded})

    priority_bonus = 0
    if profile:
        priority_bonus = _profile_priority_bonus(business, profile, rules)
        score += priority_bonus
        if priority_bonus > 0:
            relevance_matched = True

    final_score = max(0, min(100, score))
    business["score"] = final_score
    business["score_breakdown"] = {
        "mode": "profile_rules",
        "matched_rules": matched_rules,
        "priority_bonus": priority_bonus,
        "relevance_matched": relevance_matched,
        "generic_scale_without_relevance": fallback_scale if require_relevance else 1.0,
    }
    return final_score


# ---------------------------------------------------------------------------
# Main scoring entry point
# ---------------------------------------------------------------------------

def _compute_legacy_score(business: dict, search_radius_miles: float = 5.0) -> int:
    """
    Compute and return a 0–100 sponsor score for an enriched business dict.
    The result is also stored in business['score'].
    """
    tags = business.get("tags", {})

    industry       = business.get("industry", "Other")
    chain          = business.get("is_chain", False)
    website        = tags.get("website", "") or business.get("website", "")
    phone          = tags.get("phone", "") or business.get("phone", "")
    distance_miles = business.get("distance_miles", 0.0)
    audience       = business.get("target_audience", "")

    ind_s  = _industry_score(industry)
    chn_s  = _chain_score(chain)
    web_s  = _website_score(website)
    phn_s  = _phone_score(phone)
    dst_s  = _distance_score(distance_miles, max_radius=search_radius_miles)
    aud_s  = _audience_score(audience)
    hrs_s  = _opening_hours_score(tags)
    soc_s  = _social_media_score(tags)
    cmp_s  = _data_completeness_score(tags, business)
    eml_s  = _email_score(tags)

    score = max(0, min(100, ind_s + chn_s + web_s + phn_s + dst_s + aud_s
                            + hrs_s + soc_s + cmp_s + eml_s))
    business["score"] = score
    business["score_breakdown"] = {
        "Industry relevance": (ind_s,  25),
        "Local (not chain)":  (chn_s,  15),
        "Has website":        (web_s,   8),
        "Has phone":          (phn_s,   8),
        "Distance":           (dst_s,  12),
        "Audience overlap":   (aud_s,  12),
        "Opening hours":      (hrs_s,   5),
        "Social media":       (soc_s,   5),
        "Data completeness":  (cmp_s,   5),
        "Email contact":      (eml_s,   5),
    }
    return score


def compute_score(
    business: dict,
    search_radius_miles: float = 5.0,
    rules: list[dict] | None = None,
    profile: dict | None = None,
) -> int:
    """
    Compute and return a 0–100 sponsor score.

    If `rules` is provided, uses profile-driven rule scoring with a profile
    keyword priority bonus. Otherwise falls back to the legacy weighted scorer.
    """
    if rules:
        return _compute_rule_based_score(business, rules, profile)
    return _compute_legacy_score(business, search_radius_miles=search_radius_miles)


def score_color(score: int) -> str:
    """Return a Tkinter-compatible color string for the given score badge."""
    if score >= 70:
        return "#2ecc71"   # green
    if score >= 40:
        return "#f1c40f"   # yellow
    return "#e74c3c"       # red
