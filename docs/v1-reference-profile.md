# V1 Reference Profile

> **Superseded.** This was an early scratch note. The implemented design, its
> divergences from the BE source-of-truth document, and all 5 required diagrams
> now live in [reference-runtime.md](reference-runtime.md). Kept here only for
> history; do not treat it as current.

Internal implementation notes for the V1 demo and reusable routing framework.

## Project areas

| Area | Purpose |
|---|---|
| V1 Reference runtime | Tier 0 response/route -> dependency-aware classifier -> validator -> outcome |
| Comparison lab | Existing Rules, TF-IDF, Semantic, Gemini and Hybrid routers |

The reference runtime should be Python-library-first. Streamlit is a UI adapter,
not the framework boundary. HTTP service extraction is deferred.

## Demo acceptance

- Deterministic fixtures run without provider credentials.
- Demo covers `RESPONSE`, `ROUTE`, `CLARIFY`, `FALLBACK` and `REJECT`.
- Demo covers next-executable selection for independent and dependent intents.
- UI shows stage latency, rule/model version, validator result and reason code.
- Runtime never invokes a capability.
- Classifier and provider interfaces are replaceable.
- Comparison metrics and reference-runtime metrics are separate.
- Package metadata, tests, CI, license decision and optional provider dependencies
  are ready before open source.
