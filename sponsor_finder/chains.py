"""
Chain detection helpers used by enrichment.py.

  is_chain_by_tags      — fast OSM tag check (no network required)
  build_frequency_chain_set — names that appear 3+ times in a result set
"""


def is_chain_by_tags(tags: dict) -> bool:
    """
    Return True if OSM tags indicate this is a chain/franchise location.

    Priority signals (in order of reliability):
      1. brand:wikidata is set  → always a branded chain
      2. brand:wikipedia is set → almost always a chain
      3. brand tag is set AND differs from the business name → chain
         (some one-off businesses set brand = their own name, so we
          require the brand value to differ from the name)
      4. operator tag is set AND name contains operator value → chain
    """
    brand_wikidata  = tags.get("brand:wikidata", "").strip()
    brand_wikipedia = tags.get("brand:wikipedia", "").strip()
    brand           = tags.get("brand", "").strip()
    name            = tags.get("name", "").strip()
    operator        = tags.get("operator", "").strip()

    if brand_wikidata:
        return True

    if brand_wikipedia:
        return True

    if brand and brand.lower() != name.lower():
        return True

    if operator and operator.lower() != name.lower() and len(operator) > 3:
        # Weak signal — only trust if operator name is meaningful
        return True

    return False


def build_frequency_chain_set(businesses: list[dict]) -> set[str]:
    """
    Build a set of names that appear 3+ times in the result set.
    These are almost certainly chains regardless of OSM tag coverage.
    Returns lowercase names.
    """
    from collections import Counter
    name_counts = Counter(
        b.get("name", "").strip().lower()
        for b in businesses
        if b.get("name", "").strip()
    )
    return {name for name, count in name_counts.items() if count >= 3}


