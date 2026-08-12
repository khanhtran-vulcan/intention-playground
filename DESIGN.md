# Design System — Intention V1 Reference

<!-- Generated from the built two-pane Operate surface, 2026-08-08 -->

## Mode

**Operate** — routing console for acceptance demos and model checks.

## Layout

- Wide Streamlit shell (`max-width: 1480px`)
- **Left pane (~53%):** Conversation thread + chat input; intent chips after each user turn
- **Right pane (~47%):** Runtime controls → Scenario library → Output / contracts / debug

## Palette

| Token | Value | Role |
|-------|-------|------|
| ink | `#0f172a` | Primary text |
| muted | `#64748b` | Meta / labels |
| accent | `#0d9488` | Primary actions / active scenario |
| surface | `#f1f5f9` | Quiet panel fill |
| line | `#cbd5e1` | Borders |
| outcome RESPONSE | `#0f766e` | Chip / hero |
| outcome ROUTE | `#0ea5e9` | Chip / hero |
| outcome CLARIFY | `#c2410c` | Chip / hero |
| outcome FALLBACK | `#64748b` | Chip / hero |
| outcome REJECT | `#b91c1c` | Chip / hero |

## Typography

- UI sans from Streamlit defaults (Operate familiarity)
- Mono for intent names, reason codes, scenario meta

## Components

- **Intent chip** — outcome badge + intent code + reason + latency, then preview body
- **Scenario card** — id, meta line, description, full-width Load & run
- **Result hero** — latest outcome metrics on the right (does not replace thread history)
- **Category pills + search** — scenario library filter

## Motion

None authored beyond Streamlit defaults — Operate surface stays quiet.
