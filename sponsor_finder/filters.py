"""
Filter and sort logic for the business results list.
All functions are pure (no side effects) and operate on lists of dicts.
"""

from typing import Any
import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Opening-hours helper
# ---------------------------------------------------------------------------

_DAY_ABBR = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}


def _is_open_now(hours_str: str) -> bool:
    """Return True if the business is currently open based on opening_hours string.

    Handles:
    - empty / None  → False (unknown = not filterable as open)
    - "24/7"        → True
    - Standard "Mo-Fr HH:MM-HH:MM" patterns (with optional extra day segments)
    - If parsing fails → False (safe default)
    """
    if not hours_str:
        return False

    s = hours_str.strip()
    if s == "24/7":
        return True

    now = datetime.now()
    current_weekday = now.weekday()   # 0=Monday … 6=Sunday
    current_minutes = now.hour * 60 + now.minute

    # Split multiple semicolon-separated day ranges, e.g.
    # "Mo-Fr 09:00-18:00; Sa 10:00-15:00"
    segments = [seg.strip() for seg in s.split(";")]
    for segment in segments:
        if not segment:
            continue
        # Match optional day spec + time range
        m = re.match(
            r'^([A-Za-z]{2}(?:-[A-Za-z]{2})?(?:,[A-Za-z]{2}(?:-[A-Za-z]{2})?)*)\s+'
            r'(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})',
            segment,
        )
        if not m:
            continue

        day_spec, open_str, close_str = m.group(1), m.group(2), m.group(3)

        # Collect all matching day numbers from the day spec
        try:
            open_min = int(open_str[:2]) * 60 + int(open_str[3:5])
            close_min = int(close_str[:2]) * 60 + int(close_str[3:5])
        except (ValueError, IndexError):
            continue

        # Parse day spec — comma-separated groups, each group can be a range
        days_covered: set[int] = set()
        for part in day_spec.split(","):
            part = part.strip()
            range_m = re.match(r'^([A-Za-z]{2})-([A-Za-z]{2})$', part)
            if range_m:
                start_d = _DAY_ABBR.get(range_m.group(1))
                end_d   = _DAY_ABBR.get(range_m.group(2))
                if start_d is not None and end_d is not None:
                    if start_d <= end_d:
                        days_covered.update(range(start_d, end_d + 1))
                    else:
                        # Wrap-around (e.g. Sa-Tu)
                        days_covered.update(range(start_d, 7))
                        days_covered.update(range(0, end_d + 1))
            else:
                d = _DAY_ABBR.get(part)
                if d is not None:
                    days_covered.add(d)

        if current_weekday not in days_covered:
            continue

        # Check time window (handle overnight ranges like 22:00-02:00)
        if open_min <= close_min:
            if open_min <= current_minutes < close_min:
                return True
        else:
            # Overnight: open past midnight
            if current_minutes >= open_min or current_minutes < close_min:
                return True

    return False


# ---------------------------------------------------------------------------
# Standard filters
# ---------------------------------------------------------------------------

def apply_standard_filters(
    businesses: list[dict],
    name_query: str = "",
    category: str = "All",
    hide_chains: bool = False,
    min_score: int = 0,
    open_now: bool = False,
    has_wheelchair: bool = False,
    has_outdoor_seating: bool = False,
    has_delivery: bool = False,
    has_takeout: bool = False,
) -> list[dict]:
    """Return a filtered subset of businesses based on sidebar controls."""
    results = businesses

    if name_query:
        q = name_query.lower()
        results = [b for b in results if q in b.get("name", "").lower()]

    if category and category != "All":
        results = [b for b in results if b.get("industry", "") == category]

    if hide_chains:
        results = [b for b in results if not b.get("is_chain", False)]

    if min_score > 0:
        results = [b for b in results if b.get("score", 0) >= min_score]

    if open_now:
        results = [
            b for b in results
            if _is_open_now(b.get("tags", {}).get("opening_hours", "")
                            or b.get("opening_hours", ""))
        ]

    if has_wheelchair:
        results = [
            b for b in results
            if b.get("tags", {}).get("wheelchair") in ("yes", "limited")
        ]

    if has_outdoor_seating:
        results = [
            b for b in results
            if b.get("tags", {}).get("outdoor_seating") == "yes"
        ]

    if has_delivery:
        results = [
            b for b in results
            if b.get("tags", {}).get("delivery") == "yes"
        ]

    if has_takeout:
        results = [
            b for b in results
            if b.get("tags", {}).get("takeaway", b.get("tags", {}).get("takeout", "")) == "yes"
        ]

    return results


# ---------------------------------------------------------------------------
# Custom filter rule evaluation
# ---------------------------------------------------------------------------

CUSTOM_FIELDS = [
    "Score", "Name", "Industry", "Category", "Entity Type",
    "Chain", "Chain Confidence", "Num Locations", "Parent Company",
    "Has Website", "Has Phone", "Has Email", "Has Opening Hours",
    "OSM Completeness", "Distance", "Target Audience",
    "Founded Year", "Wikidata ID", "Wikidata Description",
    "AI Score", "Address",
]
CUSTOM_OPERATORS = [
    "=", "!=", ">", "<", ">=", "<=",
    "contains", "not contains", "is empty", "is not empty",
]


def _get_field_value(business: dict, field: str) -> Any:
    tags = business.get("tags", {})
    field_map = {
        "Score":                business.get("score", 0),
        "Name":                 business.get("name", ""),
        "Industry":             business.get("industry", ""),
        "Category":             business.get("industry", ""),
        "Entity Type":          business.get("entity_type", ""),
        "Chain":                business.get("is_chain", False),
        "Chain Confidence":     business.get("chain_confidence", 0),
        "Num Locations":        business.get("num_locations") or 0,
        "Parent Company":       business.get("parent_company", ""),
        "Has Website":          bool(tags.get("website") or business.get("website")),
        "Has Phone":            bool(tags.get("phone") or business.get("phone")),
        "Has Email":            bool(tags.get("email") or business.get("email")),
        "Has Opening Hours":    bool(tags.get("opening_hours") or business.get("opening_hours")),
        "OSM Completeness":     business.get("osm_completeness", 0),
        "Distance":             business.get("distance_miles", 0.0),
        "Target Audience":      business.get("target_audience", business.get("audience_overlap", "")),
        "Founded Year":         business.get("founded_year") or 0,
        "Wikidata ID":          business.get("wikidata_id", ""),
        "Wikidata Description": business.get("wikidata_description", ""),
        "AI Score":             business.get("ai_score", 0),
        "Address":              business.get("address", ""),
    }
    return field_map.get(field)


def _coerce_bool(value: str) -> bool:
    return str(value).lower().strip() in ("true", "yes", "1")


def _evaluate_rule(business: dict, rule: dict) -> bool:
    """Evaluate a single custom filter rule against a business."""
    field    = rule.get("field", "")
    operator = rule.get("operator", "=")
    value    = rule.get("value", "")

    actual = _get_field_value(business, field)

    try:
        if operator == "is empty":
            return not actual and actual != 0
        if operator == "is not empty":
            return bool(actual) or actual == 0

        if isinstance(actual, bool):
            bool_val = _coerce_bool(value)
            if operator == "=":
                return actual == bool_val
            if operator == "!=":
                return actual != bool_val
            return False

        if operator == "=":
            return str(actual).lower() == str(value).lower()
        if operator == "!=":
            return str(actual).lower() != str(value).lower()
        if operator == ">":
            return float(actual) > float(value)
        if operator == "<":
            return float(actual) < float(value)
        if operator == ">=":
            return float(actual) >= float(value)
        if operator == "<=":
            return float(actual) <= float(value)
        if operator == "contains":
            return str(value).lower() in str(actual).lower()
        if operator == "not contains":
            return str(value).lower() not in str(actual).lower()
        # Legacy alias
        if operator == "is not":
            return str(actual).lower() != str(value).lower()
    except (ValueError, TypeError):
        return False

    return False


def apply_custom_filter(
    businesses: list[dict],
    rules: list[dict],
    combine: str = "AND",
) -> list[dict]:
    """
    Apply a list of custom filter rules.

    Each rule: {"field": str, "operator": str, "value": str}
    combine: "AND" (all rules must match) or "OR" (any rule must match)
    """
    if not rules:
        return businesses

    if combine == "AND":
        return [b for b in businesses if all(_evaluate_rule(b, r) for r in rules)]
    else:  # OR
        return [b for b in businesses if any(_evaluate_rule(b, r) for r in rules)]


# ---------------------------------------------------------------------------
# Sort
# ---------------------------------------------------------------------------

SORT_KEYS = {
    "Score":            lambda b: b.get("score", 0),
    "Distance":         lambda b: b.get("distance_miles", 0.0),
    "Name":             lambda b: b.get("name", "").lower(),
    "Category":         lambda b: b.get("industry", "").lower(),
    "Completeness":     lambda b: b.get("osm_completeness", 0),
    "Has Phone":        lambda b: int(bool(b.get("phone") or b.get("tags", {}).get("phone"))),
    "Has Website":      lambda b: int(bool(b.get("website") or b.get("tags", {}).get("website"))),
    "Has Social Media": lambda b: int(bool(b.get("has_social_media"))),
    "AI Score":         lambda b: b.get("ai_score", -1),
}

# Keys that default to descending when no explicit direction is given
_DEFAULT_DESCENDING = {"Score", "Completeness", "Has Phone", "Has Website",
                       "Has Social Media", "AI Score"}


def sort_businesses(
    businesses: list[dict],
    sort_by: str = "Score",
    descending: bool | None = None,
) -> list[dict]:
    """Return a sorted copy of the businesses list.

    When *descending* is None, use the historical default behaviour:
    Score descends, all other keys ascend.
    When *descending* is explicitly True or False, use that value.
    """
    key_fn = SORT_KEYS.get(sort_by, SORT_KEYS["Score"])
    if descending is None:
        reverse = sort_by in _DEFAULT_DESCENDING
    else:
        reverse = descending
    return sorted(businesses, key=key_fn, reverse=reverse)


# ---------------------------------------------------------------------------
# Helper: collect unique categories for the dropdown
# ---------------------------------------------------------------------------

def get_categories(businesses: list[dict]) -> list[str]:
    cats = sorted({b.get("industry", "Other") for b in businesses})
    return ["All"] + cats
