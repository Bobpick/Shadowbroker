# proposal_context.json Schema (v1.0)

This schema defines the handoff format from the Autonomous Capture Runner to the BD Document Generator (`generate_bd_documents_v2.py`).

## Goals
- Strong traceability and ethics enforcement
- Clean separation between deep reasoning (runner) and polished document production (BD generator)
- Support both rich narrative and structured data

## Top-Level Structure

```json
{
  "metadata": { ... },
  "documents": [ ... ],
  "core_content": { ... },
  "reviews": { ... },
  "iteration_log": [ ... ],
  "traceability": { ... }
}
```

### metadata
- `schema_version`: "1.0"
- `generated_by`: "autonomous_runner"
- `version`: Runner version
- `run_id`: Folder name
- `timestamp`
- `model`
- `context_window`
- `opportunity_name`

### documents
Array of:
```json
{
  "id": "D01",
  "filename": "...",
  "category": "Solicitation | ISO 9001/27001 | ...",
  "path": "..."
}
```

### core_content
Contains the main deliverables with both free-text and evidence notes.

Key sections (all have `markdown` + `evidence_note`):
- `compliance_matrix`
- `win_strategy`
- `technical_approach`
- `past_performance`
- `risk_mitigation`
- `visuals_concepts`
- `executive_summary`

Future enhancement: Add `structured_rows` for compliance matrix, `risks_structured`, etc.

### reviews
Contains the full outputs from:
- `pink_team`
- `red_team`
- `neuroscientist`
- `cost_strategist`
- (Gold Team can be added later)

### iteration_log
Array of strings describing what happened during the iteration loop.

### traceability
- `all_claims_grounded`: boolean
- `documents_referenced`: array of document IDs
- `notes`: Free-text explanation of grounding approach

## Design Principles
1. Never trust the model to stay grounded — enforce it with `evidence_note` fields.
2. Keep rich narrative where it adds value.
3. Add structured fields only when they are genuinely useful to the BD generator.
4. The full audit log remains the source of truth for reasoning. This JSON is the *clean handoff artifact*.
