"""
AI scoring using llama-cpp-python (local LLM inference).
Fully offline — no API key, no token costs, no data leaving the machine.

Requires:
  - llama-cpp-python installed: pip install llama-cpp-python
  - A model downloaded via model_manager

Two modes:
  1. Score Explanation — 2-3 sentence insight per business, auto-triggered on row select
  2. AI Score Mode     — batch 0-100 scores across all results, combined with rule score
"""

import atexit
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

try:
    from sponsor_finder.model_manager import list_available_models, load_model
except ImportError:
    # Handle relative imports when running as package
    from model_manager import list_available_models, load_model

BATCH_SIZE = 10  # local models are slow — keep batches small
DEFAULT_MODEL = "llama3"

# Session caches — never re-query a business already processed this session
_explanation_cache: dict[str, str] = {}  # osm_id → explanation text
_ai_score_cache: dict[str, dict] = {}  # osm_id → {ai_score, reason}
_attribute_cache: dict[tuple, bool] = {}  # (osm_id, query) → bool

# Global LLM instance (loaded once, reused for all inferences)
_llm_instance = None
_current_model_name = None

# Thread pool for async requests (prevents UI freeze).
# max_workers=1 serialises all inference — llama-cpp-python's Llama is NOT
# thread-safe; concurrent calls into the same instance segfault the process.
_executor = ThreadPoolExecutor(max_workers=1)

# Belt-and-suspenders lock: guarantees serial LLM access even if callers
# bypass the executor and call _chat_sync directly.
_inference_lock = threading.Lock()


def _shutdown_cleanup() -> None:
    """
    Explicitly close the LLM before Python tears down module globals.
    Registered with atexit so it runs before __del__ would fire during
    interpreter shutdown — prevents the 'NoneType not callable' error
    that occurs when llama_cpp._internals functions are cleared first.
    """
    global _llm_instance, _current_model_name
    if _llm_instance is not None:
        try:
            _llm_instance.close()
        except Exception:
            pass
        _llm_instance = None
        _current_model_name = None


atexit.register(_shutdown_cleanup)


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------


def is_model_loaded() -> bool:
    """Check if a model is currently loaded in memory."""
    return _llm_instance is not None


def get_loaded_model_name() -> Optional[str]:
    """Return the name of the currently loaded model, or None."""
    return _current_model_name


def list_models() -> list[str]:
    """Return the names of models cached locally."""
    return list_available_models()


def load_default_model(model_name: str = DEFAULT_MODEL) -> bool:
    """
    Load a model into memory for inference.
    Should be called once at app startup.

    Args:
        model_name: Model to load (from cache)

    Returns True on success, False on failure.
    """
    global _llm_instance, _current_model_name

    try:
        _llm_instance = load_model(model_name)
        _current_model_name = model_name
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def unload_model() -> None:
    """Unload the current model from memory."""
    global _llm_instance, _current_model_name
    if _llm_instance is not None:
        try:
            _llm_instance.close()
        except Exception:
            pass
    _llm_instance = None
    _current_model_name = None


# ---------------------------------------------------------------------------
# Internal LLM call
# ---------------------------------------------------------------------------


def _chat_sync(prompt: str, timeout: int = 30) -> str:
    """
    Synchronous inference call using the loaded llama-cpp-python model.
    """
    if _llm_instance is None:
        raise RuntimeError("No model loaded. Call load_default_model() first.")

    with _inference_lock:
        try:
            response = _llm_instance.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.7,
            )
            content = response["choices"][0]["message"].get("content", "")
            if content and str(content).strip():
                return str(content)
        except Exception:
            pass

        try:
            completion_prompt = (
                "You are a practical assistant. Respond clearly and briefly.\n\n"
                f"{prompt}\n\nResponse:"
            )
            response = _llm_instance.create_completion(
                prompt=completion_prompt,
                max_tokens=500,
                temperature=0.7,
            )
            text = response["choices"][0].get("text", "")
            if text and str(text).strip():
                return str(text)
            raise RuntimeError("Model returned empty output")
        except Exception as e:
            raise RuntimeError(f"AI inference failed: {e}")


def _chat(prompt: str, timeout: int = 30) -> str:
    """
    Send a prompt to the model in a background thread (non-blocking).
    If timeout is exceeded, raises RuntimeError without freezing UI.
    """
    try:
        future = _executor.submit(_chat_sync, prompt, timeout)
        return future.result(timeout=timeout + 2)  # extra buffer for thread overhead
    except Exception as e:
        raise RuntimeError(f"AI request failed: {e}")


# ---------------------------------------------------------------------------
# Mode 1: Score Explanation
# ---------------------------------------------------------------------------


def _profile_prompt_context(profile: dict | None) -> str:
    """Build a short prompt snippet from profile options to steer AI behavior."""
    if not profile:
        return ""

    lines: list[str] = []
    audience_keywords = [str(k).strip() for k in profile.get("audience_keywords", []) if str(k).strip()]
    priority_keywords = [str(k).strip() for k in profile.get("priority_keywords", []) if str(k).strip()]

    if audience_keywords:
        lines.append(f"- Audience keywords: {', '.join(audience_keywords[:20])}")
    if priority_keywords:
        lines.append(f"- Priority keywords: {', '.join(priority_keywords[:20])}")

    if bool(profile.get("require_relevance_for_generic")):
        scale = float(profile.get("generic_scale_without_relevance", 1.0) or 1.0)
        scale = max(0.0, min(1.0, scale))
        lines.append(f"- Relevance gate: de-emphasize generic businesses without keyword overlap (scale={scale:.2f})")

    bonus_cap = profile.get("priority_bonus_cap")
    if bonus_cap is not None:
        try:
            lines.append(f"- Priority bonus cap: {int(bonus_cap)}")
        except Exception:
            pass

    if not lines:
        return ""
    return "\nProfile tuning:\n" + "\n".join(lines)


def get_explanation(business: dict, profile_desc: str, profile: dict | None = None) -> str:
    """
    Generate a 2-3 sentence explanation of why this business scored the way it did,
    plus a suggested outreach angle. Cached per osm_id for the session.

    Returns the explanation string, or an error message on failure.
    """
    if not is_model_loaded():
        return "(AI not ready: no model loaded)"

    osm_id = business.get("osm_id", "")
    if osm_id and osm_id in _explanation_cache:
        return _explanation_cache[osm_id]

    tags = business.get("tags", {})
    has_email = bool(tags.get("email") or tags.get("contact:email"))

    prompt = (
        f"You are helping evaluate local businesses as potential sponsors for: {profile_desc}\n\n"
        f"{_profile_prompt_context(profile)}\n\n"
        "Business details:\n"
        f"- Name: {business.get('name', '')}\n"
        f"- Industry: {business.get('industry', '')}\n"
        f"- Entity type: {business.get('entity_type', 'Unknown')} "
        f"(chain confidence: {business.get('chain_confidence', 0)}%)\n"
        f"- Distance: {business.get('distance_miles', 0):.1f} miles from event location\n"
        f"- Has website: {bool(business.get('website'))}, "
        f"Has phone: {bool(business.get('phone'))}, "
        f"Has email: {has_email}\n"
        f"- Target audience: {business.get('target_audience', 'Unknown')}\n"
        f"- Rule-based score: {business.get('score', 0)}/100\n\n"
        "In 2-3 sentences: explain why this business scored the way it did, and suggest "
        "a specific outreach angle. Be direct and practical. No fluff."
    )

    try:
        result = _chat(prompt, timeout=30).strip()
    except Exception as e:
        result = f"(AI unavailable: {e})"

    if osm_id:
        _explanation_cache[osm_id] = result
    return result


def get_cached_explanation(osm_id: str) -> str | None:
    """Return a cached explanation, or None if not yet generated."""
    return _explanation_cache.get(osm_id)


# ---------------------------------------------------------------------------
# Mode 2: AI Score Mode (batch)
# ---------------------------------------------------------------------------

def _normalize_keywords(values: list) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        token = str(value).strip().lower()
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def _business_text_blob(business: dict) -> str:
    tags = business.get("tags", {}) or {}
    parts = [
        business.get("name", ""),
        business.get("industry", ""),
        business.get("category", ""),
        business.get("target_audience", ""),
        tags.get("description", ""),
        tags.get("shop", ""),
        tags.get("amenity", ""),
        tags.get("office", ""),
        tags.get("leisure", ""),
        tags.get("cuisine", ""),
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _apply_profile_ai_adjustments(base_score: int, business: dict, profile: dict | None) -> tuple[int, list[str]]:
    """
    Deterministic post-processing so profile options reliably influence ai_score,
    even if the local model output is noisy.
    """
    score = max(0, min(100, int(base_score)))
    if not profile:
        return score, []

    text_blob = _business_text_blob(business)
    audience_keywords = _normalize_keywords(profile.get("audience_keywords", []))
    priority_keywords = _normalize_keywords(profile.get("priority_keywords", []))

    matched_audience = [kw for kw in audience_keywords if kw in text_blob]
    matched_priority = [kw for kw in priority_keywords if kw in text_blob]

    adjustments: list[str] = []

    if matched_audience:
        audience_bonus = min(10, len(matched_audience) * 2)
        score += audience_bonus
        adjustments.append(f"+{audience_bonus} audience-match")

    if matched_priority:
        try:
            cap = int(profile.get("priority_bonus_cap", 0) or 0)
        except Exception:
            cap = 0
        if cap > 0:
            priority_bonus = min(cap, len(matched_priority) * 3)
            if priority_bonus > 0:
                score += priority_bonus
                adjustments.append(f"+{priority_bonus} priority-keyword")

    if bool(profile.get("require_relevance_for_generic")) and not (matched_audience or matched_priority):
        try:
            scale = float(profile.get("generic_scale_without_relevance", 1.0) or 1.0)
        except Exception:
            scale = 1.0
        scale = max(0.0, min(1.0, scale))
        if scale < 1.0:
            score = int(round(score * scale))
            adjustments.append(f"relevance-scale x{scale:.2f}")

    return max(0, min(100, score)), adjustments


def score_batch(businesses: list[dict], profile_desc: str, profile: dict | None = None) -> list[dict]:
    """
    Score up to BATCH_SIZE businesses that are not already cached.
    Returns a list of {osm_id, ai_score, reason} dicts for newly scored items.
    Caches all results in _ai_score_cache.
    """
    if not is_model_loaded():
        return []

    to_score = [b for b in businesses
                if b.get("osm_id", "") not in _ai_score_cache][:BATCH_SIZE]
    if not to_score:
        return []

    business_list = [
        {
            "osm_id":           b.get("osm_id", ""),
            "name":             b.get("name", ""),
            "industry":         b.get("industry", ""),
            "entity_type":      b.get("entity_type", "Unknown"),
            "chain_confidence": b.get("chain_confidence", 0),
            "distance_mi":      round(b.get("distance_miles", 0), 2),
            "has_website":      bool(b.get("website")),
            "has_phone":        bool(b.get("phone")),
            "has_email":        bool(
                b.get("tags", {}).get("email") or
                b.get("tags", {}).get("contact:email")
            ),
            "audience_overlap": b.get("target_audience", ""),
        }
        for b in to_score
    ]

    prompt = (
        f"You are scoring local businesses as potential sponsors for: {profile_desc}\n\n"
        f"{_profile_prompt_context(profile)}\n\n"
        "Score each business 0-100 based on sponsor fit. Consider: industry relevance, "
        "local vs chain, professionalism signals, audience overlap with the event.\n\n"
        "Respond ONLY with a valid JSON array, no explanation, no markdown:\n"
        '[{"osm_id": "...", "ai_score": 85, "reason": "one sentence"}, ...]\n\n'
        "Businesses:\n"
        f"{json.dumps(business_list, indent=2)}"
    )

    try:
        raw = _chat(prompt, timeout=30)

        # Try direct JSON parse first
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # If that fails, extract JSON array from response text
            # Find first '[' and last ']' — more robust than greedy regex
            start = raw.find('[')
            end = raw.rfind(']')
            if start == -1 or end == -1 or end <= start:
                return []  # No JSON array found
            parsed = json.loads(raw[start:end+1])

        results = []
        lookup_by_id = {str(b.get("osm_id", "")): b for b in to_score}

        for item in parsed:
            osm_id = item.get("osm_id", "")
            raw_ai_score = max(0, min(100, int(item.get("ai_score", 50))))
            business = lookup_by_id.get(str(osm_id), {})
            adjusted_score, adjustments = _apply_profile_ai_adjustments(raw_ai_score, business, profile)

            base_reason = str(item.get("reason", "")).strip()
            if adjustments:
                tuning_note = "Profile tuning: " + ", ".join(adjustments)
                reason = f"{base_reason} | {tuning_note}" if base_reason else tuning_note
            else:
                reason = base_reason

            entry = {
                "osm_id":   osm_id,
                "ai_score": adjusted_score,
                "reason":   reason,
            }
            if osm_id:
                _ai_score_cache[osm_id] = entry
            results.append(entry)
        return results

    except Exception:
        return []


def get_cached_ai_score(osm_id: str) -> dict | None:
    """Return a cached AI score entry, or None if not yet scored."""
    return _ai_score_cache.get(osm_id)


def compute_combined_score(rule_score: int, ai_score: int, ai_weight: float = 0.5) -> int:
    """
    Weighted average of rule score and AI score.
    ai_weight in [0.0, 1.0]; rule_weight = 1 - ai_weight.
    """
    rule_weight = 1.0 - ai_weight
    return max(0, min(100, round(rule_score * rule_weight + ai_score * ai_weight)))


def check_attribute(business: dict, query: str) -> bool:
    """
    Ask the loaded LLM whether a business matches a natural-language attribute.
    E.g. query = "has outdoor parking", "serves alcohol", "good for families".

    Returns True if the model says yes, False otherwise.
    Cached by (osm_id, normalized query) for the session.
    """
    if not is_model_loaded():
        return False

    osm_id = business.get("osm_id", "")
    cache_key = (osm_id, query.strip().lower())
    if cache_key in _attribute_cache:
        return _attribute_cache[cache_key]

    tags = business.get("tags", {}) or {}
    # Build a compact tags summary, skipping address fields
    skip = {"addr:housenumber", "addr:street", "addr:city", "addr:state",
            "addr:postcode", "name"}
    tag_parts = [f"{k}={v}" for k, v in list(tags.items())[:20] if k not in skip]
    tags_str = ", ".join(tag_parts) if tag_parts else "none"

    prompt = (
        f"Business: {business.get('name', '')}\n"
        f"Industry: {business.get('industry', '')}\n"
        f"Category: {business.get('category', '')}\n"
        f"OSM tags: {tags_str}\n\n"
        f'Does this business likely have or offer: "{query}"?\n'
        "Reply with ONLY the single word yes or no."
    )

    try:
        # max_tokens=5 is enough for "yes"/"no" — keeps inference fast
        with _inference_lock:
            response = _llm_instance.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=5,
                temperature=0.0,
            )
        raw = response["choices"][0]["message"]["content"].strip().lower()
        result = raw.startswith("yes")
    except Exception:
        result = False

    if osm_id:
        _attribute_cache[cache_key] = result
    return result


def clear_attribute_cache() -> None:
    """Clear the AI attribute filter cache."""
    _attribute_cache.clear()


def clear_session_cache():
    """Clear all session caches (e.g. after a new search)."""
    _explanation_cache.clear()
    _ai_score_cache.clear()
    _attribute_cache.clear()


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------

#: Curated list shown in the "Download Model" picker.
RECOMMENDED_MODELS = [
    ("llama3",        "Meta Llama 3 8B — fast, recommended",        "~4.0 GB"),
    ("phi3",          "Microsoft Phi-3 Mini — smallest / fastest",   "~2.2 GB"),
    ("orca-mini:3b",  "Orca Mini 3B — lightweight alternative",      "~2.0 GB"),
    ("mistral",       "Mistral 7B — strong general reasoning",       "~4.1 GB"),
    ("falcon",        "GPT4All Falcon 7B — general purpose",         "~4.2 GB"),
]


def download_model_async(
    model_name: str,
    on_progress: callable,
    on_done: callable,
    on_error: callable,
    cancellation_token=None,
) -> None:
    """
    Download a model in a background thread.

    Args:
        model_name: Model name or custom GGUF URL
        on_progress: Called as on_progress(status_msg, progress_pct)
        on_done: Called on success
        on_error: Called as on_error(error_msg) on failure
        cancellation_token: Object with .is_cancelled() method
    """
    try:
        from sponsor_finder.model_manager import download_model_async as mm_download
    except ImportError:
        from model_manager import download_model_async as mm_download

    mm_download(model_name, on_progress, on_done, on_error, cancellation_token)


def delete_model(model_name: str) -> bool:
    """
    Delete a model from the local cache.

    Args:
        model_name: Model name to delete

    Returns True on success, False on failure.
    """
    try:
        from sponsor_finder.model_manager import delete_model as mm_delete
    except ImportError:
        from model_manager import delete_model as mm_delete

    return mm_delete(model_name)


def is_ai_ready() -> bool:
    """
    Check if AI features are available (a model is loaded and ready for inference).
    """
    return is_model_loaded()


# Backward compatibility alias
def is_ollama_running() -> bool:
    """
    Deprecated: Use is_ai_ready() instead.
    Check if AI features are available (a model is loaded and ready for inference).
    """
    return is_ai_ready()


def pick_best_model(models: list[str]) -> str:
    """
    Pick the best model from a list of available models.
    Prefers DEFAULT_MODEL if available, otherwise returns the first one.

    Args:
        models: List of available model names

    Returns:
        Best model name, or empty string if list is empty
    """
    if not models:
        return ""
    if DEFAULT_MODEL in models:
        return DEFAULT_MODEL
    return models[0]


def pull_model(
    model_name: str,
    on_progress: callable,
    on_done: callable,
    on_error: callable,
    cancellation_token=None,
) -> None:
    """
    Alias for download_model_async for backwards compatibility.
    Downloads a model in a background thread.
    """
    download_model_async(model_name, on_progress, on_done, on_error, cancellation_token)
