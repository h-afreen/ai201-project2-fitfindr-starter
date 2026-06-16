# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the 40 mock secondhand listings for items matching the user's description,
applying optional size and price filters, then ranks the matches by relevance.
This is a pure-Python tool — no LLM call.

**Input parameters:**
- `description` (str): keywords describing the desired item (e.g., "vintage graphic tee").
- `size` (str | None): size to filter by, matched case-insensitively (e.g., "M" matches "S/M"). `None` skips size filtering.
- `max_price` (float | None): inclusive price ceiling. `None` skips price filtering.

**What it returns:**
A `list[dict]` of matching listings sorted by relevance score (best match first).
Each listing dict contains: `id`, `title`, `description`, `category`, `style_tags`,
`size`, `condition`, `price`, `colors`, `brand`, `platform`.
Returns an empty list `[]` when nothing matches — it never raises.

**Scoring logic (weighted by field):**
Transform the description into lowercase and split it into keywords. For each keyword, add points
based on where it matches in the listing:
- match in `style_tags` → +3 (curated style signal, strongest intent match)
- match in `title` → +2
- match in `description` → +1
A listing's score is the sum across all keywords. Drop listings scoring 0, then
sort by score descending.

**What happens if it fails or returns nothing:**
The tool itself returns `[]` — it does not raise or fabricate results. The *agent*
(not this tool) detects the empty list, sets `session["error"]` to a friendly
"no matches" message, and stops before calling `suggest_outfit`.

---

### Tool 2: suggest_outfit

**What it does:**
Given a thrifted item and the user's wardrobe, calls the LLM (Groq,
`llama-3.3-70b-versatile`, temperature ~0.7) to suggest 1–2 complete outfits
that style the new item.

**Input parameters:**
- `new_item` (dict): the listing dict the user is considering buying.
- `wardrobe` (dict): a wardrobe dict with an `items` key (list of wardrobe item dicts). May be empty.

**What it returns:**
A non-empty string describing 1–2 outfit ideas. Two paths depending on the wardrobe:
- **Wardrobe has items:** the prompt lists the user's named pieces, and the LLM
  suggests outfits combining the new item with *specific named pieces* from the wardrobe.
- **Wardrobe empty (new user):** the prompt asks for *general* styling advice —
  what kinds of pieces pair well with the item and what vibe/occasion it suits.

**What happens if it fails or returns nothing:**
The empty-wardrobe case is handled by branching to the general-advice prompt rather
than erroring — so the tool always returns useful text. (If the LLM call itself
raised, that would surface as a session error in the agent loop.)

---

### Tool 3: create_fit_card

**What it does:**
Turns the outfit suggestion into a short, shareable OOTD-style social caption.
Calls the LLM (Groq, `llama-3.3-70b-versatile`, temperature ~0.9 for variety).

**Input parameters:**
- `outfit` (str): the outfit suggestion string returned by `suggest_outfit`.
- `new_item` (dict): the listing dict for the thrifted item (used for name, price, platform).

**What it returns:**
A 2–4 sentence caption usable as an Instagram/TikTok post. It should:
- feel casual and authentic (an OOTD post, not a product description),
- mention the item name, price, and platform naturally (once each),
- capture the outfit vibe in specific terms,
- read differently for different inputs (hence the higher temperature).

**What happens if it fails or returns nothing:**
First it guards against an empty/whitespace-only `outfit` — in that case it returns
a descriptive error *string* (e.g., "Can't build a fit card without an outfit.")
rather than raising. The agent only reaches this tool on the happy path, so this
guard is a safety net.

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**

The agent runs a linear pipeline with one branch (an early exit on no results).
It is deterministic — the *order* of tools is fixed; what changes is whether the
pipeline completes or stops early, and which prompt path Tool 2 takes.

1. **Initialize** a fresh session dict with `_new_session(query, wardrobe)`.
2. **Parse the query** into `description` / `size` / `max_price` using Groq
   tool-calling: a forced function call (`extract_search_params`) returns the three
   fields as validated JSON. Wrapped in try/except with a fallback that treats the
   whole query as `description` and leaves the filters as `None`. Result stored in
   `session["parsed"]`.
3. **Call `search_listings`** with the parsed params. Store results in
   `session["search_results"]`.
   - **Branch — no results:** if the list is empty, set `session["error"]` to a
     friendly message and `return` immediately. The agent does NOT call
     `suggest_outfit` with empty input.
4. **Select** the top-ranked listing (`search_results[0]`) into
   `session["selected_item"]`.
5. **Call `suggest_outfit`** with the selected item and the wardrobe. The tool
   internally picks the wardrobe vs. empty-wardrobe prompt path. Store the string
   in `session["outfit_suggestion"]`.
6. **Call `create_fit_card`** with the outfit suggestion and selected item. Store
   the caption in `session["fit_card"]`.
7. **Return** the session dict.

**How does it know it's done?** There is no open-ended reasoning loop — the agent
is done when it either hits the no-results early exit (with `error` set) or reaches
the end of step 7 (with `fit_card` populated and `error` is `None`). The caller
inspects `session["error"]` first to tell the two outcomes apart.

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (created by `_new_session`) is the single source of truth
for one interaction. Each step reads from it and writes its output back, so tools
stay decoupled — none of them call each other directly; they communicate only
through the session.

Fields tracked:

| Field | Written by | Read by |
|-------|-----------|---------|
| `query` | `_new_session` | parse step |
| `parsed` (description/size/max_price) | parse step | `search_listings` |
| `search_results` | `search_listings` | select step |
| `selected_item` | select step | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | `_new_session` | `suggest_outfit` |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card` |
| `fit_card` | `create_fit_card` | caller / UI |
| `error` | any step that exits early | caller / UI (checked first) |

The flow of derived state: `query → parsed → search_results → selected_item →
outfit_suggestion → fit_card`. Because everything lives in one dict, the agent
function returns it whole, and the UI maps fields straight to panels.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| (query parse) | LLM omits the tool call / returns bad JSON | Caught in try/except; fall back to using the whole query as `description` with `size`/`max_price` = `None`. Pipeline continues. |
| search_listings | No results match the query | Tool returns `[]`. Agent sets `session["error"]` to a friendly "no matches, try broadening your search" message and returns early — does NOT call `suggest_outfit`. |
| suggest_outfit | Wardrobe is empty | Tool branches to a general-styling-advice prompt instead of erroring, so it always returns useful text for a new user. |
| create_fit_card | Outfit input is missing or incomplete | Tool guards against empty/whitespace `outfit` and returns a descriptive error *string* rather than raising. |

---

## Architecture

```
        User query + wardrobe choice
                    │
                    ▼
        handle_query()  (app.py / Gradio)
                    │
                    ▼
        run_agent(query, wardrobe)  ───────────────┐
                    │                              │
                    ▼                              │   reads & writes
        ┌─────────────────────────┐               │   every step
        │ Step 2: parse query      │               │
        │ Groq tool-calling        │◄──────────────┤
        │ extract_search_params    │   bad JSON?   │
        └───────────┬─────────────┘   └─► fallback │
                    │ parsed{desc,size,price}      │
                    ▼                              │
        ┌─────────────────────────┐               │   ┌──────────────────┐
        │ search_listings (no LLM) │◄──────────────┼──►│   session dict   │
        └───────────┬─────────────┘               │   │ (single source   │
                    │                              │   │  of truth)       │
            results empty? ──yes──► set error ─────┼──►│  query, parsed,  │
                    │ no                           │   │  search_results, │
                    ▼                              │   │  selected_item,  │
        select search_results[0] ──────────────────┤   │  wardrobe,       │
                    │ selected_item                │   │  outfit_sugg.,   │
                    ▼                              │   │  fit_card, error │
        ┌─────────────────────────┐               │   └──────────────────┘
        │ suggest_outfit (LLM)     │◄──────────────┤
        │  ├ wardrobe has items →  │               │
        │  │   specific outfits    │               │
        │  └ empty → general advice│               │
        └───────────┬─────────────┘               │
                    │ outfit_suggestion            │
                    ▼                              │
        ┌─────────────────────────┐               │
        │ create_fit_card (LLM)    │◄──────────────┘
        │  empty outfit? → err str │
        └───────────┬─────────────┘
                    │ fit_card
                    ▼
        return session ─► UI maps fields to 3 panels
        (error set → show in panel 1, others blank)
```

**Trigger summary:** each tool fires in fixed order; the only branch points are the
no-results early exit (after `search_listings`) and the wardrobe-empty prompt path
(inside `suggest_outfit`). All state flows through the session dict — tools never
call each other directly.

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

I'll use **Claude (in Claude Code)** to implement each tool, one at a time, feeding it
the relevant Tool section of this planning.md as the spec.

- `search_listings`: give Claude the Tool 1 spec (params, return shape, the weighted
  scoring scheme: style_tags +3 / title +2 / description +1) and the `load_listings()`
  helper signature. Expected output: a pure-Python function, no LLM. **Verify** by
  running it against 3 queries — "vintage graphic tee", "size M" filter, and
  "under $20" — and checking the top results make sense and empty queries return `[]`.
- `suggest_outfit`: give Claude the Tool 2 spec plus the wardrobe schema and the chosen
  model (`llama-3.3-70b-versatile`, temp ~0.7). Expected output: a function with the
  two prompt paths. **Verify** by calling it once with the example wardrobe and once
  with the empty wardrobe and confirming the empty case still returns useful advice.
- `create_fit_card`: give Claude the Tool 3 spec (caption rules, temp ~0.9, the empty
  -outfit guard). **Verify** by running it twice on the same item and confirming the
  captions differ and each mentions name/price/platform once.

**Milestone 4 — Planning loop and state management:**

I'll give Claude the **Planning Loop**, **State Management**, and **Architecture**
sections above, plus the `run_agent` docstring, and ask it to implement the loop
including the Groq tool-calling parse step and the no-results early exit. Expected
output: `run_agent` populating the session dict in order and returning it.
**Verify** with the two CLI cases already in `agent.py` (`__main__`): the happy-path
graphic-tee query should populate `selected_item`/`outfit_suggestion`/`fit_card` with
`error=None`, and the "designer ballgown size XXS under $5" query should set `error`
and leave the outputs `None`. Finally wire `handle_query` in `app.py` and test the
same queries through the Gradio UI.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Initialize + parse.**
`run_agent` creates the session, then calls Groq with the forced `extract_search_params`
tool. The model returns structured args:
`{"description": "vintage graphic tee", "size": null, "max_price": 30.0}`.
(The wardrobe-related text "baggy jeans and chunky sneakers" is left in the query but
isn't needed for search — it informs styling later via the actual wardrobe.)
Stored in `session["parsed"]`.

**Step 2 — Search.**
Calls `search_listings("vintage graphic tee", size=None, max_price=30.0)`. It filters
out anything over $30, then scores by weighted keyword overlap. A vintage band tee
tagged `["vintage","graphic","tee"]` scores high (style_tags hits = +3 each); a plain
$25 shirt with only a description match scores low. Returns a sorted list; stored in
`session["search_results"]`. It's non-empty, so no early exit.

**Step 3 — Select.**
Takes `search_results[0]` (the top-scored tee) into `session["selected_item"]`.

**Step 4 — Suggest outfit.**
Calls `suggest_outfit(selected_item, example_wardrobe)`. The wardrobe has items, so the
LLM gets the named pieces and suggests outfits like: "Tuck the tee into your baggy
straight-leg jeans, layer the vintage black denim jacket, finish with the chunky white
sneakers." Stored in `session["outfit_suggestion"]`.

**Step 5 — Fit card.**
Calls `create_fit_card(outfit_suggestion, selected_item)`. The LLM (temp ~0.9) writes a
2–4 sentence caption mentioning the tee's name, price, and platform once each. Stored in
`session["fit_card"]`. Returns the session.

**Final output to user:**
The Gradio UI shows three panels — the **top listing** (title, price, platform,
condition), the **outfit idea** from step 4, and the **fit card** caption from step 5.
`session["error"]` is `None`, so all three panels populate. (For the no-results query
"designer ballgown size XXS under $5", step 2 returns `[]`, the agent sets `error`, and
only panel 1 shows the friendly "no matches" message.)
