"""
Business enrichment: chain detection, industry tagging, target audience inference.
"""

import requests
from chains import is_chain_by_tags, build_frequency_chain_set

# ---------------------------------------------------------------------------
# Chain detection via Wikidata
# ---------------------------------------------------------------------------

# Module-level cache: name (lowercase) → bool
# Prevents hitting the API more than once per unique name per session.
_wikidata_cache: dict[str, bool] = {}

CHAIN_KEYWORDS = [
    "chain", "franchise", "restaurant chain", "retail chain",
    "fast food", "multinational", "corporation", "convenience store",
    "supermarket chain", "clothing chain", "pharmacy chain",
    "hotel chain", "coffee chain", "gas station",
]

WIKIDATA_API = "https://www.wikidata.org/w/api.php"


def is_chain_wikidata(name: str) -> bool:
    """
    Query the Wikidata search API for the business name and inspect the
    top result's description for chain/franchise keywords.

    Results are cached by name so each unique name is only looked up once.
    Returns False on any network error so a bad connection never crashes enrichment.
    """
    key = name.strip().lower()
    if not key:
        return False

    if key in _wikidata_cache:
        return _wikidata_cache[key]

    try:
        r = requests.get(
            WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "format": "json",
                "limit": 1,
            },
            timeout=5,
            headers={"User-Agent": "RedlineSponsorFinder/1.0"},
        )
        results = r.json().get("search", [])
        if results:
            desc = results[0].get("description", "").lower()
            result = any(kw in desc for kw in CHAIN_KEYWORDS)
        else:
            result = False
    except Exception:
        # Network error, timeout, or parse failure — assume not a chain
        result = False

    _wikidata_cache[key] = result
    return result


def _is_chain(business: dict, frequency_chain_set: set | None = None) -> bool:
    """
    Three-tier chain detection:
      1. OSM tag signals (instant, no network) — brand:wikidata, brand, operator
      2. Wikidata API description lookup (network, cached per name)
      3. Frequency analysis — same name appears 3+ times in result set
    """
    tags = business.get("tags", {})

    # Tier 1: fast OSM tag check
    if is_chain_by_tags(tags):
        return True

    # Tier 2: Wikidata lookup using the business name
    name = business.get("name", tags.get("name", ""))
    if name and is_chain_wikidata(name):
        return True

    # Tier 3: frequency-based (same name seen 3+ times in result set)
    if frequency_chain_set:
        if name.strip().lower() in frequency_chain_set:
            return True

    return False

# ---------------------------------------------------------------------------
# Industry tag mapping  OSM tag value → human-readable category
# ---------------------------------------------------------------------------
INDUSTRY_MAP = {
    # Automotive
    "car_repair": "Automotive Shop",
    "car_wash": "Car Wash",
    "car_parts": "Auto Parts",
    "tyres": "Tire Shop",
    "tires": "Tire Shop",
    "fuel": "Gas Station",
    "motorcycle": "Motorcycle Shop",
    "car": "Car Dealership",
    "car_rental": "Car Rental",
    "vehicle_inspection": "Vehicle Inspection",
    "detailing": "Auto Detailing",

    # Food & Drink
    "restaurant": "Restaurant",
    "fast_food": "Fast Food",
    "cafe": "Cafe",
    "bar": "Bar",
    "pub": "Bar",
    "nightclub": "Nightclub",
    "food": "Food",
    "bakery": "Bakery",
    "deli": "Deli",
    "ice_cream": "Ice Cream",
    "pizza": "Pizza",
    "brewery": "Brewery",

    # Health & Fitness
    "gym": "Gym",
    "fitness_centre": "Gym",
    "sports": "Sports",
    "spa": "Spa",
    "massage": "Massage",
    "pharmacy": "Pharmacy",
    "dentist": "Dentist",
    "doctor": "Medical",
    "clinic": "Medical",
    "hospital": "Medical",
    "optician": "Optician",
    "beauty": "Beauty Salon",
    "hairdresser": "Hair Salon",
    "barber": "Barber",

    # Retail
    "supermarket": "Grocery",
    "convenience": "Convenience Store",
    "clothes": "Clothing Store",
    "shoes": "Shoe Store",
    "electronics": "Electronics",
    "mobile_phone": "Mobile Phone",
    "computer": "Computer Store",
    "hardware": "Hardware Store",
    "furniture": "Furniture",
    "department_store": "Department Store",
    "mall": "Shopping Mall",
    "gift": "Gift Shop",
    "toys": "Toy Store",
    "books": "Bookstore",
    "music": "Music Store",
    "outdoor": "Outdoor/Sports Store",
    "sporting_goods": "Sporting Goods",
    "pet": "Pet Store",
    "florist": "Florist",
    "jewelry": "Jewelry",
    "watch": "Watch Store",
    "optometrist": "Optician",

    # Services
    "bank": "Bank",
    "atm": "ATM",
    "post_office": "Post Office",
    "insurance": "Insurance",
    "real_estate": "Real Estate",
    "travel_agency": "Travel Agency",
    "laundry": "Laundry",
    "dry_cleaning": "Dry Cleaning",
    "printing": "Printing",
    "copyshop": "Print Shop",
    "signmaker": "Sign Shop",
    "photo": "Photography",
    "tattoo": "Tattoo Parlor",
    "piercing": "Piercing Studio",

    # Entertainment / Leisure
    "hotel": "Hotel",
    "motel": "Hotel",
    "hostel": "Hotel",
    "cinema": "Cinema",
    "theatre": "Theatre",
    "bowling_alley": "Bowling Alley",
    "arcade": "Arcade",
    "escape_game": "Escape Room",
    "miniature_golf": "Mini Golf",
    "go-kart": "Go-Kart Track",
    "karting": "Go-Kart Track",
    "paintball": "Paintball",
    "laser_tag": "Laser Tag",
    "amusement_arcade": "Arcade",
    "park": "Park",
    "stadium": "Stadium",
    "sports_centre": "Sports Center",

    # Professional / Office
    "office": "Office",
    "company": "Business",
    "it": "IT Company",
    "accountant": "Accounting",
    "lawyer": "Law Office",
    "advertising": "Marketing/Advertising",
    "engineering": "Engineering",
    "financial": "Financial Services",

    # Miscellaneous
    "storage": "Storage",
    "warehouse": "Warehouse",
    "car_dealer": "Car Dealership",
    "bicycle": "Bicycle Shop",
    "boat": "Boat Shop",
}

KEYWORD_INDUSTRY_HINTS = (
    (("wrap", "vinyl wrap"), "Auto Wrap Shop"),
    (("detail", "detailing"), "Auto Detailing"),
    (("performance", "dyno", "tuning"), "Performance Shop"),
    (("auto repair", "car repair", "mechanic", "transmission", "brake"), "Automotive Shop"),
    (("body shop", "collision", "paint"), "Auto Body Shop"),
    (("sign", "signage", "graphics"), "Sign Shop"),
    (("window tint", "tint"), "Tint Shop"),
    (("wheel", "rim"), "Wheel/Tire Shop"),
    (("watch", "timepiece"), "Watch Store"),
)

# ---------------------------------------------------------------------------
# Target audience inference  category → inferred audience string
# ---------------------------------------------------------------------------
AUDIENCE_MAP = {
    "Automotive Shop":        "Car enthusiasts, vehicle owners",
    "Car Wash":               "Car enthusiasts, vehicle owners",
    "Auto Parts":             "Car enthusiasts, DIY mechanics",
    "Tire Shop":              "Car enthusiasts, vehicle owners",
    "Gas Station":            "Drivers, commuters",
    "Motorcycle Shop":        "Motorcycle enthusiasts, riders",
    "Car Dealership":         "Car buyers, vehicle enthusiasts",
    "Car Rental":             "Travelers, commuters",
    "Auto Detailing":         "Car enthusiasts, detailing hobbyists",
    "Go-Kart Track":          "Car enthusiasts, young adults 16–35",
    "Restaurant":             "General public, families, young adults",
    "Fast Food":              "General public, budget-conscious diners",
    "Cafe":                   "Young adults 18–35, professionals",
    "Bar":                    "Adults 21+, nightlife crowd",
    "Pub":                    "Adults 21+, nightlife crowd",
    "Nightclub":              "Young adults 21–30, nightlife crowd",
    "Brewery":                "Craft beer enthusiasts, adults 21+",
    "Gym":                    "Fitness-focused adults 18–45",
    "Sports":                 "Athletes, active young adults",
    "Sporting Goods":         "Athletes, outdoor enthusiasts",
    "Outdoor/Sports Store":   "Outdoor and sports enthusiasts",
    "Electronics":            "Tech-savvy young adults 18–35",
    "Clothing Store":         "Young adults 16–35, fashion-conscious",
    "Hotel":                  "Travelers, event attendees",
    "Convenience Store":      "Commuters, local community",
    "Grocery":                "Families, general public",
    "Tattoo Parlor":          "Young adults 18–35, counter-culture crowd",
    "Barber":                 "Young men 16–40",
    "Hair Salon":             "General public",
    "Beauty Salon":           "Adults, primarily women",
    "Bowling Alley":          "Families, young adults, groups",
    "Arcade":                 "Young adults 16–30, gamers",
    "Cinema":                 "Families, young adults",
}

DEFAULT_AUDIENCE = "General public"

# ── Industry tier classification ──────────────────────────────────────────
# "primary"  — directly automotive / car-culture relevant
# "secondary" — enthusiast-adjacent (food, lifestyle, apparel, etc.)
# "excluded" — never relevant as car meet sponsors (medical, legal, finance…)
# "other"    — everything else (neutral)

_EXCLUDED_INDUSTRIES = {
    "Medical", "Dentist", "Pharmacy", "Hospital", "Optician", "Spa", "Massage",
    "Bank", "ATM", "Insurance", "Real Estate", "Travel Agency", "Law Office",
    "Post Office", "Accounting", "Financial Services", "Engineering",
    "Dry Cleaning", "Laundry", "Storage", "Warehouse", "IT Company",
    "Florist", "Bookstore", "Toy Store",
}

_PRIMARY_INDUSTRIES = {
    "Automotive Shop", "Auto Parts", "Auto Detailing", "Auto Wrap Shop",
    "Auto Body Shop", "Tire Shop", "Wheel/Tire Shop", "Tint Shop",
    "Car Wash", "Performance Shop", "Car Dealership", "Motorcycle Shop",
    "Go-Kart Track", "Vehicle Inspection", "Car Rental", "Gas Station",
    "Motorsports Shop",
}

_SECONDARY_INDUSTRIES = {
    "Gym", "Sporting Goods", "Outdoor/Sports Store", "Sports",
    "Tattoo Parlor", "Barber", "Electronics", "Arcade", "Bowling Alley",
    "Restaurant", "Cafe", "Bar", "Brewery", "Nightclub",
    "Print Shop", "Sign Shop", "Photography", "Watch Store",
    "Jewelry", "Clothing Store", "Fast Food", "Pizza", "Bakery",
    "Convenience Store", "Hair Salon",
}

# Keywords whose presence in a business name signals automotive relevance
_CAR_NAME_KEYWORDS = {
    "auto", "automotive", "car", "cars", "vehicle", "motor", "motors",
    "tire", "tires", "tyre", "tyres", "wheel", "wheels", "rim", "rims",
    "detail", "detailing", "wash", "wax", "wrap", "vinyl", "tint",
    "performance", "racing", "speed", "tuning", "dyno", "drift", "stance",
    "mechanic", "repair", "body shop", "collision",
    "lube", "oil change", "muffler", "exhaust", "brake", "transmission",
    "jdm", "euro", "muscle", "sport", "turbo", "supercar", "supercharged",
    "pit", "track", "autocross", "karting", "kart",
}

# Social media tag keys (also referenced in scoring.py — keep in sync)
_SOCIAL_MEDIA_KEYS = {
    "contact:facebook", "facebook",
    "contact:instagram", "instagram",
    "contact:twitter", "twitter",
    "contact:youtube", "youtube",
    "contact:tiktok", "tiktok",
}


def get_industry_relevance_tier(industry: str) -> str:
    """Classify an industry label into a broad relevance tier.

    Returns one of: "primary", "secondary", "excluded", "other"
    """
    if industry in _EXCLUDED_INDUSTRIES:
        return "excluded"
    if industry in _PRIMARY_INDUSTRIES:
        return "primary"
    if industry in _SECONDARY_INDUSTRIES:
        return "secondary"
    return "other"


def name_has_car_keywords(name: str) -> bool:
    """Return True if the business name contains automotive-relevant keywords."""
    name_lower = name.lower()
    return any(kw in name_lower for kw in _CAR_NAME_KEYWORDS)


def build_audience_overlap(industry: str, tags: dict, name: str) -> str:
    """Build a richer audience description by combining industry, name, and OSM tags.

    The result is a comma-joined string of audience descriptors; profile rules that
    use `audience_overlap contains "car"` will fire when any automotive signal is found.
    """
    parts: list[str] = []

    # Base audience from industry map
    base = AUDIENCE_MAP.get(industry, DEFAULT_AUDIENCE)
    parts.append(base)

    # Business name automotive signals
    name_lower = name.lower()
    if any(kw in name_lower for kw in {"car", "auto", "motor", "racing", "tuning",
                                        "wheel", "tire", "tyre", "drift", "performance",
                                        "mechanic", "detailing", "wrap", "vinyl", "tint"}):
        if "car enthusiasts" not in base.lower():
            parts.append("car enthusiasts")
        if "automotive" not in base.lower():
            parts.append("automotive community")

    # OSM description / cuisine tags
    text = (tags.get("description", "") + " " + tags.get("cuisine", "")).lower()
    if any(kw in text for kw in {"car", "auto", "vehicle", "motorsport", "racing"}):
        if "car enthusiasts" not in " ".join(parts).lower():
            parts.append("car enthusiasts")

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for p in parts:
        key = p.lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(p)

    return ", ".join(deduped)


# ---------------------------------------------------------------------------
# OSM category (primary key label)
# ---------------------------------------------------------------------------

def get_osm_category(tags: dict) -> str:
    """Return the primary OSM key as a human-readable label (Shop, Amenity, etc.)."""
    for key, label in (
        ("shop",    "Shop"),
        ("amenity", "Amenity"),
        ("office",  "Office"),
        ("leisure", "Leisure"),
        ("tourism", "Tourism"),
    ):
        if tags.get(key):
            return label
    return "Other"


# ---------------------------------------------------------------------------
# Industry tagging
# ---------------------------------------------------------------------------

def get_industry(tags: dict) -> str:
    """Derive a human-readable industry/category from OSM tags."""
    for key in ("shop", "amenity", "office", "leisure", "tourism"):
        value = tags.get(key, "").lower()
        if value in INDUSTRY_MAP:
            return INDUSTRY_MAP[value]

    text_blob = " ".join(
        [
            tags.get("name", ""),
            tags.get("description", ""),
            tags.get("shop", ""),
            tags.get("amenity", ""),
            tags.get("office", ""),
            tags.get("leisure", ""),
        ]
    ).lower()
    for hints, industry in KEYWORD_INDUSTRY_HINTS:
        if any(hint in text_blob for hint in hints):
            return industry

    # Fallback: return the raw tag value capitalized
    for key in ("shop", "amenity", "office", "leisure"):
        value = tags.get(key, "")
        if value and value not in ("yes", "no"):
            return value.replace("_", " ").title()

    return "Other"


# ---------------------------------------------------------------------------
# Target audience inference
# ---------------------------------------------------------------------------

def get_target_audience(industry: str) -> str:
    """Return a human-readable target audience for the given industry."""
    return AUDIENCE_MAP.get(industry, DEFAULT_AUDIENCE)


# ---------------------------------------------------------------------------
# Establishment status
# ---------------------------------------------------------------------------

def get_establishment_status(tags: dict, chain: bool) -> str:
    """Return 'Established' or 'Unknown' based on available signals."""
    if chain:
        return "Established"
    if tags.get("opening_hours"):
        return "Established"
    if tags.get("phone") or tags.get("website"):
        return "Established"
    return "Unknown"


# ---------------------------------------------------------------------------
# Main enrichment entry point
# ---------------------------------------------------------------------------

def enrich(business: dict, frequency_chain_set: set | None = None) -> dict:
    """
    Accept a raw business dict (from search.py) and return it with
    enrichment fields added in-place.

    Expected input keys: name, tags, distance_miles
    Added keys: industry, target_audience, is_chain, establishment_status
    """
    tags = business.get("tags", {})

    industry = get_industry(tags)
    chain = _is_chain(business, frequency_chain_set)
    audience = get_target_audience(industry)
    status = get_establishment_status(tags, chain)

    business["category"] = get_osm_category(tags)
    business["industry"] = industry
    business["is_chain"] = chain
    business["target_audience"] = audience
    # Richer audience overlap incorporating name and description signals
    audience_overlap = build_audience_overlap(industry, tags, business.get("name", ""))
    business["audience_overlap"] = audience_overlap
    business["establishment_status"] = status

    # Additional data-point fields for profile scoring
    business["industry_relevance_tier"] = get_industry_relevance_tier(industry)
    business["name_has_car_keywords"] = name_has_car_keywords(business.get("name", ""))
    business["has_social_media"] = any(
        str(tags.get(k, "")).strip() for k in _SOCIAL_MEDIA_KEYS
    )
    business["distance_mi"] = business.get("distance_miles", 0.0)

    phone = tags.get("phone") or tags.get("contact:phone") or business.get("phone", "")
    email = tags.get("email") or tags.get("contact:email") or business.get("email", "")
    website = tags.get("website") or tags.get("contact:website") or business.get("website", "")
    opening_hours = tags.get("opening_hours") or business.get("opening_hours", "")

    business["has_phone"] = bool(str(phone).strip())
    business["has_email"] = bool(str(email).strip())
    business["has_website"] = bool(str(website).strip())
    business["has_opening_hours"] = bool(str(opening_hours).strip())

    completeness_keys = ("name", "phone", "email", "website", "opening_hours", "addr:street", "addr:city")
    present = 0
    for key in completeness_keys:
        if key == "phone":
            value = phone
        elif key == "email":
            value = email
        elif key == "website":
            value = website
        elif key == "opening_hours":
            value = opening_hours
        else:
            value = tags.get(key, "")
        if str(value).strip():
            present += 1

    business["osm_completeness"] = round((present / len(completeness_keys)) * 100)
    business["chain_confidence"] = 80 if chain else 0
    business.setdefault("entity_type", "Franchise" if chain else "Local")
    business.setdefault("num_locations", 0)
    business.setdefault("parent_company", "")
    business.setdefault("founded_year", 0)

    return business
