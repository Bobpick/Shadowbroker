# Capture System — Shadowbroker

This directory contains the prompt architecture and supporting materials for high-stakes DoD, NASA, and federal R&D proposal work (SBIR/STTR, BAAs, RFPs, etc.) as an SDVOSB in advanced materials, sensors, communications, and C-UAS technologies.

## Primary Artifact

**`/prompts/elite-capture-orchestrator-v2.md`**

The master prompt (currently v2.1). Paste this (plus your solicitation + supporting documents) into a capable model session. It will:

- Execute a disciplined 5-phase capture process using a realistic **lean three-event color team cadence** (Pink / Red / Gold) designed for small SDVOSBs with limited B&P resources.
- Activate and direct a team of specialized agents, including:
  - Neuroscientist (Cognitive Alignment Framework)
  - Cost & Affordability Strategist (lean execution, ROM realism, affordability positioning)
  - Full Red Team as the core of the adversarial color team event
- Explicitly leverage ISO 9001 and ISO 27001 certifications as audited evidence of quality and information security discipline.
- Treat cost realism and lean advantages as first-class strategic elements ("money always has a play").
- Maintain a living compliance matrix.
- Iterate with mandatory quality gates (Neuroscientist + Red Team + Cost Strategist sign-off + Reviewer Experience Rubric) until the package is genuinely excellent, compliant, and reviewer-friendly.

## Agent Reference Cards

**`/agents/agent-reference-cards.md`**

Lightweight, copy-paste ready charters for each agent role. Use these when:
- Manually tasking human team members or color team reviewers.
- Spawning sub-agents in environments that support orchestration (e.g., this Grok TUI via `spawn_subagent`).
- Creating focused task prompts under deadline pressure.

The cards are deliberately concise and follow consistent structure so they impose minimal cognitive load when you are already deep in capture mode.

## Local Ollama Tools

**`/ollama_capture_tool/`** contains two complementary tools:

### 1. Conversational Tool (`main.py`)
Good when you want to stay in the loop and steer.

### 2. Autonomous Hands-Off Runner (`autonomous_runner.py`) ← **This is what you asked for**

This is the "load documents → click Start → go get coffee → come back to a finished package" tool.

It autonomously executes:
- Phase A (full compliance matrix + gap analysis)
- Phase B (win strategy + cost/affordability + lean advantages + ISO leverage)
- Pink Team review
- Core drafting (technical approach, past performance, risk, visuals, exec summary)
- Full Red Team + Neuroscientist (Cognitive Alignment) + Cost Strategist reviews
- Up to 3 iterations of fixes + re-reviews against the gates
- Gold Team final polish
- Clean assembled Markdown package

**See `ollama_capture_tool/AUTONOMOUS_README.md` for instructions.**

This mode is deliberately designed for long-running, low-supervision execution on your local `cogito:70b` (or other) model. A full run can take many hours — that is the intended use case.

**Every prompt and response is logged** in the run directory for your ethics audit.

## Quick Start Recommendation

For most real work, use the Ollama Capture Tool. Reserve the raw prompt + sub-agents (via this Grok environment) for the most complex or highest-stakes efforts where you want maximum orchestration power and parallel agent reviews.

## Key Design Principles (Why This Architecture Exists)

This system was deliberately evolved from earlier single-agent versions using the same Cognitive Alignment Framework it directs the Neuroscientist agent to apply. The goals are:

- **Mental Model Alignment** — The process and language match how professional capture managers and government reviewers actually think and work.
- **Reduced Cognitive Load** — Clear phases, explicit input/output contracts, mandatory output formats, and scannable rubrics instead of vague instructions.
- **Concreteness** — Operational definitions (Reviewer Experience Rubric, Mandatory Output Format for the Neuroscientist, specific quality gates) replace "do good work" abstractions.
- **Ethical Grounding** — Ruthless "never invent" rules + conservative TRL/impact standards are non-negotiable.
- **Mandatory Iteration Discipline** — Neuroscientist and Red Team have explicit challenge rights. No early victory declarations.

## How to Use on a New Opportunity

1. Copy the full text of `elite-capture-orchestrator-v2.md`.
2. In a new session, provide:
   - The complete solicitation (BAA, SBIR topic, RFP, attachments, evaluation criteria, etc.).
   - All relevant company supporting documents for *this* opportunity (capability statements, past proposals, IP summaries, certifications, DD214, white papers, etc.).
   - Any constraints (page limits, due date, format requirements, teaming status, etc.).
3. The Orchestrator will begin with Phase A (requirements intelligence and compliance matrix) and proceed through the full process.

## Directory Layout

```
capture/
├── README.md
├── prompts/
│   └── elite-capture-orchestrator-v2.md     # Master prompt (primary artifact)
└── agents/
    └── agent-reference-cards.md             # Lightweight charters for tasking
```

## Version History

- **v2.1 (current)**: Added realistic lean color team cadence (Pink/Red/Gold) designed for small SDVOSBs, new Cost & Affordability Strategist agent, explicit ISO 9001/27001 leveraging, and strengthened cost realism / lean execution focus throughout. All changes respect limited B&P resources while treating money and affordability as first-class discriminators.
- **v2.0**: Full multi-agent architecture with explicit agent charters, orchestration protocol, Reviewer Experience Rubric, and mandatory Neuroscientist output format. Critiqued and refined using the Cognitive Alignment Framework.
- **v1.x (prior)**: Strong single-agent disciplined process. Still effective but lacked defined sub-agent roles and cognitive alignment enforcement mechanisms.

## Notes for This Environment

When using inside the Grok TUI / Shadowbroker workspace, you can leverage `spawn_subagent` (and related tools) to run specialized agents in parallel with focused prompts derived from the agent cards. The architecture is designed to work equally well in pure single-model sessions through explicit role-switching.

For actual proposal work, always supply the most recent and specific company artifacts available. The system is only as good as the evidence it is given to work with.

---

**Primary contact / owner:** Bob (this repo)  
**Last major update:** See git history for the prompt file.
