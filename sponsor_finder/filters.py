"""
Filter and sort logic for the business results list.
All functions are pure (no side effects) and operate on lists of dicts.
"""

from typing import Any


# ---------------------------------------------------------------------------
# Standard filters
# ---------------------------------------------------------------------------

def apply_standard_filters(
    businesses: list[dict],
    name_query: str = "",
    category: str = "All",
    hide_chains: bool = False,
    min_score: int = 0,
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

    return results


# ---------------------------------------------------------------------------
# Custom filter rule evaluation
# ---------------------------------------------------------------------------

CUSTOM_FIELDS = ["Score", "Category", "Chain", "Has Website", "Has Phone",
                 "Distance", "Target Audience"]
CUSTOM_OPERATORS = [">", "<", "=", "contains", "is not"]


def _get_field_value(business: dict, field: str) -> Any:
    tags = business.get("tags", {})
    field_map = {
        "Score":           business.get("score", 0),
        "Category":        business.get("industry", ""),
        "Chain":           business.get("is_chain", False),
        "Has Website":     bool(tags.get("website") or business.get("website")),
        "Has Phone":       bool(tags.get("phone") or business.get("phone")),
        "Distance":        business.get("distance_miles", 0.0),
        "Target Audience": business.get("target_audience", ""),
    }
    return field_map.get(field)


def _evaluate_rule(business: dict, rule: dict) -> bool:
    """Evaluate a single custom filter rule against a business."""
    field    = rule.get("field", "")
    operator = rule.get("operator", "=")
    value    = rule.get("value", "")

    actual = _get_field_value(business, field)

    try:
        if operator == ">":
            return float(actual) > float(value)
        if operator == "<":
            return float(actual) < float(value)
        if operator == "=":
            # Boolean fields
            if isinstance(actual, bool):
                return actual == (value.lower() in ("true", "yes", "1"))
            return str(actual).lower() == str(value).lower()
        if operator == "contains":
            return str(value).lower() in str(actual).lower()
        if operator == "is not":
            if isinstance(actual, bool):
                return actual != (value.lower() in ("true", "yes", "1"))
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
    "Score":    lambda b: b.get("score", 0),
    "Distance": lambda b: b.get("distance_miles", 0.0),
    "Name":     lambda b: b.get("name", "").lower(),
    "Category": lambda b: b.get("industry", "").lower(),
}


def sort_businesses(businesses: list[dict], sort_by: str = "Score") -> list[dict]:
    """Return a sorted copy of the businesses list."""
    key_fn = SORT_KEYS.get(sort_by, SORT_KEYS["Score"])
    reverse = sort_by in ("Score",)   # higher score = better → descending
    return sorted(businesses, key=key_fn, reverse=reverse)


# ---------------------------------------------------------------------------
# Helper: collect unique categories for the dropdown
# ---------------------------------------------------------------------------

def get_categories(businesses: list[dict]) -> list[str]:
    cats = sorted({b.get("industry", "Other") for b in businesses})
    return ["All"] + cats
