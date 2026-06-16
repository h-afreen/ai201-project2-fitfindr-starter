"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Model used by the LLM-backed tools (suggest_outfit, create_fit_card).
MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    Scoring (weighted by field): for each keyword in the description, a match in
    style_tags adds 3, in the title adds 2, and in the description adds 1.
    """
    listings = load_listings()

    keywords = description.lower().split()

    results = []
    for listing in listings:
        # --- filters: skip anything that fails a hard constraint ---
        if max_price is not None and listing["price"] > max_price:
            continue
        if size is not None and size.lower() not in listing["size"].lower():
            continue

        # --- weighted keyword scoring ---
        title = listing["title"].lower()
        desc = listing["description"].lower()
        tags = [t.lower() for t in listing["style_tags"]]

        score = 0
        for kw in keywords:
            if any(kw in tag for tag in tags):
                score += 3
            if kw in title:
                score += 2
            if kw in desc:
                score += 1

        if score > 0:
            results.append((score, listing))

    # highest score first
    results.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _score, listing in results]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    Uses Groq (llama-3.3-70b-versatile, temperature ~0.7) with two prompt paths
    depending on whether the wardrobe has items.
    """
    client = _get_groq_client()

    item_desc = (
        f"{new_item['title']} (category: {new_item['category']}, "
        f"colors: {', '.join(new_item['colors'])}, "
        f"style: {', '.join(new_item['style_tags'])})"
    )

    items = wardrobe.get("items", [])

    if not items:
        # New user — no wardrobe to pull from. Give general styling advice.
        prompt = (
            f"A shopper is considering this secondhand item:\n{item_desc}\n\n"
            "They have not entered a wardrobe yet. Suggest 1-2 outfit ideas in "
            "general terms: what kinds of pieces (colors, categories, styles) pair "
            "well with it, and what vibe or occasion it suits. Keep it concise and "
            "practical."
        )
    else:
        # Format the user's actual wardrobe so the LLM can name specific pieces.
        wardrobe_lines = "\n".join(
            f"- {it['name']} ({it['category']}, {', '.join(it['colors'])})"
            for it in items
        )
        prompt = (
            f"A shopper is considering this secondhand item:\n{item_desc}\n\n"
            f"Here is their existing wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that style the new item using specific "
            "named pieces from their wardrobe above. Refer to the wardrobe pieces "
            "by name. Keep it concise and practical."
        )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return response.choices[0].message.content


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    Uses Groq (llama-3.3-70b-versatile, temperature ~0.9 for variety).
    """
    # Guard: can't write a caption with no outfit to describe.
    if not outfit or not outfit.strip():
        return "Can't build a fit card without an outfit suggestion."

    client = _get_groq_client()

    prompt = (
        "Write a short, shareable Instagram/TikTok OOTD caption for a secondhand find.\n\n"
        f"Item: {new_item['title']}\n"
        f"Price: ${new_item['price']}\n"
        f"Platform: {new_item['platform']}\n"
        f"Outfit: {outfit}\n\n"
        "Guidelines:\n"
        "- 2-4 sentences, casual and authentic (a real OOTD post, not a product description).\n"
        "- Mention the item name, price, and platform naturally, once each.\n"
        "- Capture the outfit vibe in specific terms.\n"
        "Return only the caption text."
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
    )
    return response.choices[0].message.content
