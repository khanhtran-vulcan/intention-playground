# HANDOFF — Intention V1 Reference UI (post-redesign) — UX review

**Audience:** Independent UX / interaction-flow reviewer  
**Constraint for reviewer:** Do **not** assume access to source code, repo, or screenshots unless the owner attaches them. This file is the sole product brief. Judge from the described experience only.  
**Product owner complaint (verbatim):** Current UI/UX is still very poor; needs an honest, actionable review of layout, density, and interaction flows. *(Original complaint predated the redesign below; treat as standing bar — re-score the **current** build.)*  
**Date of this handoff:** 2026-08-08  
**Surface under review:** Streamlit app **Intention V1 Reference** — acceptance demo + routing playground (`make run`). Not the Comparison Lab.  
**Stack / platform constraints:** Must remain **Streamlit ~1.46**; session state only; prefer Fake provider for offline flow review. Full Comparison Lab often segfaults on macOS — out of scope.

> **Update 2026-08-08 late:** Post-redesign scored **25/40**. A structural pass shipped: thread vs result role split, historical pane locks (contracts hidden), scenario select + `Run as new conversation` with confirm, recovery CTAs, ≤4 scenario filters, bounded conversation scroll. Re-verify DoD + first viewport at 1366×768 / 1280×720 live.

---

## 1. What you are reviewing

### Product in one sentence
An **operator console** for engineers/PMs to try **Intention Detection & Routing V1**: send a user message (or load a fixture scenario), see which **outcome** the router chose, inspect contracts, optionally run a **demo mock** capability.

### Who uses it
- Backend / AI engineers validating routing behavior  
- PMs / reviewers checking acceptance scenarios  
- Job: load scenario or chat → read outcome → clarify or run mock → inspect contracts / debug when needed  

### What success looks like for the user
1. Within one glance of the first viewport: know where conversation lives, where the **current result** is, and how to send input.  
2. Load a known scenario without hunting a long dropdown (search + category + Run).  
3. See conversation history with compact intent outcomes inline.  
4. After each turn, immediately know: outcome, intent, acceptance PASS/MISMATCH (if scenario), latency/cost cue, and the next action (clarify options / demo mock / keep chatting).  
5. Keep Setup, Inspect JSON, and Advanced tools secondary — reachable, not competing with the primary loop.

### What this is NOT
- Not a production messenger or consumer chat product  
- Not a marketing landing page  
- Not the Comparison Lab (rules / TF-IDF / semantic / Gemini compare tabs)  
- Mock capability is **demo-only** and must stay labeled as mock  
- Scenario dataset is a **smoke / acceptance** suite, not production quality evidence  

---

## 2. Domain glossary

| Term | Meaning | Why the reviewer needs it |
| --- | --- | --- |
| **Outcome** | One of `RESPONSE`, `ROUTE`, `CLARIFY`, `FALLBACK`, `REJECT` per turn | Drives UI hierarchy, CTAs, and copy |
| **RESPONSE** | Direct reply (greeting/FAQ or LLM text) | Next: continue chatting |
| **ROUTE** | Call a capability with name + arguments | Next: optional **Run demo mock** on the turn |
| **CLARIFY** | Ask one blocking question (≤3 option cards; free text OK) | Options appear **inline on the turn**; or type in dock |
| **FALLBACK** | No safe route → treat as normal chat | Soft path; may be missing API key |
| **REJECT** | Policy block | Hard stop — must not feel like soft chat |
| **Intent / name** | Capability id when `ROUTE` (e.g. `create_ai_art`) | Shown in result hero + chips |
| **Acceptance** | Expected vs actual outcome(/name) after a scenario Run | PASS / MISMATCH badge in Current result |
| **Tools allowlist** | Client-supported intents; removing one can force FALLBACK | Lives in Setup popover |
| **Clarification turn count** | Max 3 clarifications then forced FALLBACK | Shown as `n/3` near clarify UI |
| **Public / Internal / Mock** | Three distinct contract surfaces | Inspect tabs — must not blur |
| **Deterministic Fake** | Offline keyword/scripted router provider | Preferred for UX flow review without keys |
| **Interaction dock** | Bottom of left pane: Write message \| Pick scenario | Single entry for input vs fixtures |

Active executable intents in the demo: `create_ai_art`, `chat_with_image`, `image_to_image_generation`, `real_time_search`, `deep_research` (+ non-executable `unknown`).

---

## 3. How to run (optional)

```bash
make setup
make run
# open http://localhost:8501
```

Prefer **Deterministic Fake** in Setup for offline UX review. Live Gemini/OpenAI need keys in `.env` (not required for this review).

If you **cannot** run the app: review entirely from sections 4–8. Do not invent screenshots.

---

## 4. Current architecture / screen map

### Fact vs inference
- **Fact:** Wide canvas (`max-width: min(1440px, 94vw)`); two columns ≈ **1.7 : 1**; header + Setup **popover**; left = Conversation + Interaction dock; right = Current result first, then collapsed Inspect / Advanced.  
- **Fact:** Scenario Run always starts a **new conversation**. Historical turn Inspect shows **summary only**; full Public/Internal/Mock contracts are for the **latest** turn.  
- **Fact:** Primary CTAs for CLARIFY options and Run demo mock are **inline on the latest intent turn** in the thread (not only in the right pane).  
- **Inference:** Visual language is cool slate / teal “operator console” (custom CSS), not consumer chat branding.  
- **Unknown:** Exact pixel measurements on a given laptop viewport; Streamlit chrome height; whether `st.chat_input` always stays in the first viewport on short displays.  
- **Unknown:** Dedicated narrow/mobile layout — **not** built; Streamlit default stacking on narrow widths (**platform + design debt**).

### Sketch — first viewport (desktop, intended)

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│  Intention V1 Reference                          [ Setup ▾ ]                │
│  Acceptance playground · Fake · tools=…                                     │
├────────────────────────────────────────┬────────────────────────────────────┤
│  CONVERSATION                          │  CURRENT RESULT                    │
│  N messages · M intent turns           │                                    │
│  ┌──────────────────────────────────┐  │  ┌──────────────────────────────┐  │
│  │ empty: “Start with a message…”   │  │  │ empty: run message/scenario  │  │
│  │   [Write a message] [Pick…]      │  │  │   to see outcome here        │  │
│  │ — OR —                           │  │  │ — OR —                       │  │
│  │ user bubble                      │  │  │ [OUTCOME badge]              │  │
│  │ intent chip (ROUTE·name · ms)    │  │  │ intent name                  │  │
│  │   preview / JSON args            │  │  │ Expected → Actual · PASS     │  │
│  │   [Run demo mock · name]         │  │  │ response / route JSON        │  │
│  │   (if CLARIFY: option buttons)   │  │  │ ms · tokens · $ · reason     │  │
│  └──────────────────────────────────┘  │  └──────────────────────────────┘  │
│  INTERACTION                           │  ▸ Inspect (Public|Internal|Mock) │
│  [ Write message | Pick scenario ]     │  ▸ Advanced (debug/prompt/bench)  │
│  chat_input  OR  search+pills+list     │                                    │
└────────────────────────────────────────┴────────────────────────────────────┘
```

### Component inventory (as the operator sees it)

| Region | Controls |
| --- | --- |
| Header | Title, config caption, **Setup** popover |
| Setup popover | Provider, model (if live), tools multiselect, image for next message, Reset with confirm |
| Conversation | Chat bubbles; intent chips; Inspect turn; inline mock / clarify / REJECT warning |
| Dock — Write | Segmented control + `chat_input` + config caption |
| Dock — Pick | Search, category pills (All / RESPONSE / ROUTE / CLARIFY / REJECT / More), scrollable list, **Run** = new conversation |
| Current result | Outcome hero, acceptance strip, body, meta caption; demo mock summary if run |
| Inspect | Tabs/sections: Public Client Contract, Internal Trace, Mock Capability |
| Advanced | Debug bundle, classifier prompt, benchmark harness, “How V1 works” |

### Reading order (intended information budget)
1. Header identity + current config summary  
2. Left: what was said / which outcomes fired  
3. Right top: **what just happened** (outcome + acceptance)  
4. Dock: next input  
5. Inspect / Advanced only when debugging  

---

## 5. Primary interaction / runtime flows

### Flow A — Free chat (Write message)
1. Open app (empty thread + empty Current result).  
2. Empty state offers Write / Pick; or use dock → **Write message**.  
3. Type in chat input → turn runs → user bubble + intent chip appear; Current result updates.  
4. If `ROUTE`: primary button **Run demo mock · {name}** on the chip; after mock, DEMO MOCK message may appear + suggested next-turn buttons.  
5. If `CLARIFY`: option buttons on the chip; free text also via dock. Cap `n/3`.  
6. If `REJECT`: warning on turn + error in Current result (hard stop messaging).  
7. Click **Inspect turn** on a chip → Current result shows that turn; historical = summary only; button **Show latest turn** available.

**Review focus:** First-run clarity; whether CTAs zigzag between panes; empty-state quality; outcome hierarchy in Current result vs chip duplication.

### Flow B — Scenario acceptance (Pick scenario)
1. Dock → **Pick scenario**.  
2. Search and/or category pills; scan list (`id`, Expected outcome/name, description).  
3. Click **Run** → conversation **resets**, fixture loads, first user text submitted, acceptance expectations stored.  
4. Current result shows Expected → Actual · **PASS** or **MISMATCH**.  
5. Continue with clarify / mock as in Flow A if the outcome requires it.

**Review focus:** Whether scenario mode feels like “run a test” vs buried admin; density of the list (height ~220px scroll); risk of accidental reset when switching scenarios; clarity of PASS/MISMATCH.

### Flow C — Setup / provider failure
1. Open **Setup** popover.  
2. Switch to Gemini/OpenAI without key → error in Setup; live turn may **FALLBACK** with missing-credentials guidance pointing back to Setup / Fake.  
3. Reset conversation: confirm step when thread non-empty; keeps provider/tools.

**Review focus:** Discoverability of Setup; destructive reset safety; error recovery path length.

### Flow D — Inspect & Advanced (secondary)
1. After a result, expand **Inspect** → Public / Internal / Mock (latest turn’s contracts; caption if a historical turn is selected).  
2. Expand **Advanced** → debug JSON, prompt panel, benchmark run, explainer.

**Review focus:** Whether secondary surfaces stay demoted; cognitive load if left expanded by habit; labeling honesty for Mock.

---

## 6. Known pain points (hypotheses)

Treat as hypotheses to confirm/deny on the **current** build (many were P0s on the *previous* UI):

1. **First viewport still fails** — conversation + dock + result may not fit; Streamlit chrome / chat_input placement pushes result or dock below fold (**platform debt** likely).  
2. **Duplicated outcome surfaces** — chip on the left and hero on the right may still feel redundant or conflicting.  
3. **Scenario list density** — fixed-height scroll + Run per row may still feel cramped or “admin panel-ish.”  
4. **Inline CTAs + dock** — clarify options on the turn vs “type below” may split attention.  
5. **Historical inspect** — summary-only may confuse operators who expect full contracts for any selected turn.  
6. **Narrow / mobile** — no dedicated breakpoint; stacked columns may bury Current result (**design + platform debt**).  
7. **Scroll/focus after rerun** — Streamlit full rerun may jump scroll position (**platform debt**; known P2).  
8. **Copy / language policy** — mixed English operator jargon; no full language polish pass.  
9. **Owner standing bar** — “still very poor” may still hold if information budget / spatial hierarchy remain weak despite P0 checklist completion.

---

## 7. Principles / constraints to honor

1. **One primary loop:** input or scenario → outcome → next action; config/debug secondary.  
2. **Conversation is source of truth** for what was asked and which intent fired.  
3. **Demo honesty:** Mock and Internal never look like Client wire.  
4. **REJECT ≠ soft FALLBACK** in copy or layout.  
5. **Scenario Run = new conversation** (product lock).  
6. **Full contracts = latest turn only** (product lock).  
7. Stay on Streamlit; do not propose rewriting the stack unless as an explicit out-of-scope alternative.  
8. Label **platform debt** (Streamlit limits) vs **design debt** (choices we could fix in-app).

---

## 8. Review brief

### A. Verdict on the operator job
1. Does the current IA let an engineer/PM complete Flows A–B without hunting?  
2. Does the first viewport communicate: talk here / result here / configure there?

### B. Top UX failures (spatial / flow evidence)
1. Name failures with reference to the wireframe or flow steps above.  
2. Separate **platform debt** vs **design debt**.  
3. Call out any regression or leftover from the 15/40 failure modes (narrow canvas, result below fold, zigzag CTAs, scenario-as-admin, no information budget).

### C. Target IA sketch
1. ASCII target for first viewport + one secondary state (e.g. CLARIFY or scenario mode).  
2. What to cut or demote further.

### D. Prioritized backlog
1. P0 / P1 / P2 table: problem → change → why → effort S/M/L → risk → debt class.  
2. Do **not** require implementing; recommendations only.

### E. Definition of Done for a “good enough” redesign
Propose a short DoD checklist the owner can use to accept or reject the next UI pass (spatial + flow, not pixel polish).

Heuristic scoring is optional; do not invent a score system the owner did not ask for.

---

## 9. Expected deliverable format

Reply with:

1. **Verdict** (1–2 sentences) — does this console serve the operator job?  
2. **Top 3 failures** (with evidence from §4–§5)  
3. **Target sketch** (ASCII is enough)  
4. **P0 / P1 / P2 table** (problem → change → why → effort S/M/L → risk → platform vs design debt)  
5. **Definition of Done** (checklist)  
6. **Out of scope / rejected directions**  
7. **Open questions** for the owner (only if they block a recommendation)

Do **not** paste large code. Do **not** require reading the repository. State assumptions when the handoff is ambiguous.

---

## 10. Change log relevant to this review

| When | Change | Intent |
| --- | --- | --- |
| Earlier 2026-08-08 | Two-pane Conversation \| Settings+Output | First redesign; later scored 15/40 |
| 2026-08-08 evening | Wide canvas; Setup popover; Current result first; Write/Pick dock; inline CLARIFY + demo mock; Expected/Actual PASS-MISMATCH; Inspect + Advanced demotion | Address P0/P1 from independent review |
| This handoff | Freeze post-redesign UX for re-review | Independent validation of DoD |

---

## 11. Non-goals for this review

- Redesigning Comparison Lab  
- Changing routing algorithm, taxonomy, or BE §10 wire contracts  
- Production capability implementation (mock stays mock)  
- Full visual brand system / marketing polish  
- Perfect mobile app experience (note gaps only)  
- Implementing the backlog in the same reply as the review  

---

## 12. Contact / ownership

- Surface owner: Intention playground / V1 Reference UI  
- This handoff supersedes informal chat memory and the pre-redesign layout description for the review session  

**End of handoff.**
