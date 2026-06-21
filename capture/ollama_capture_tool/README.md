# Ethical Ollama Capture Assistant

A local, auditable tool that lets you run the full **Elite Capture Orchestrator v2.1** (Lean Color Team + Cost + ISO) against real solicitations using your own Ollama instance (`cogito:70b` recommended).

Designed for a highly ethical SDVOSB professional who refuses to cheat, exaggerate, or invent content to win government work.

## Core Principles Built Into This Tool

- The model can **only** use content that actually exists in the documents you load.
- Gaps must be explicitly called out.
- Every single prompt sent to the model is written to a timestamped log file on your machine.
- You remain 100% responsible for what is ultimately submitted.
- The tool is deliberately transparent and conservative by design.

## Setup

1. **Install dependencies**
   ```bash
   cd capture/ollama_capture_tool
   pip install -r requirements.txt
   ```

2. **Make sure Ollama is running**
   ```bash
   ollama serve
   ```

3. **Pull the model you want to use**
   ```bash
   ollama pull cogito:70b
   ```
   (Warning: 70B models are very large and slow on consumer hardware. You can use a smaller model for testing.)

4. **Verify the master prompt exists**
   The tool loads the real prompt from:
   `../prompts/elite-capture-orchestrator-v2.md`
   (relative to this directory). Do not move or rename it.

## How to Use

1. Run the tool:
   ```bash
   python main.py
   ```

2. Fill in the **Opportunity Name**.

3. Select the **Solicitation** file (BAA, SBIR topic, RFP, etc.).

4. Add all relevant **Supporting Documents**:
   - Capability statements
   - ISO 9001 and ISO 27001 certificates / audit reports (very important)
   - Past performance
   - IP / technology summaries (DragonScale, etc.)
   - Financial or cost data (if you want realistic ROM work)
   - White papers, DD214, etc.

5. Click **INITIALIZE SESSION**.

   The tool will:
   - Extract raw text from every file
   - Load the full v2.1 orchestrator prompt + strong ethics block
   - Send everything to your local model
   - Log the entire initial prompt to `session_logs/`

6. Review the Phase A output (compliance matrix + alignment assessment).

7. Use the bottom text box to drive the rest of the process conversationally:
   - "Now run Phase B — develop win strategy and cost positioning"
   - "Execute a full Pink Team review on the current draft"
   - "Draft the technical approach section using only the evidence in D03 and D07"
   - "Act as Red Team and stress-test the cost narrative for lean deliverability"

8. Everything stays in the conversation history. The model remembers the documents because they were provided in the first turn.

9. When ready, click **Save Current Markdown Output** and copy/paste the clean Markdown into your ODT / LibreOffice document.

## Important Notes for Ethical Use

- **Context length**: Large 70B models have big context windows, but there is still a limit. If you load 15 very long PDFs, you may hit limits. The tool currently sends full text on the first turn. Future versions can add smarter indexing.
- **Speed**: First turn with `cogito:70b` on a full package will be slow (sometimes 5–15+ minutes). Subsequent turns are faster because the heavy context is already in the conversation.
- **Temperature**: The tool hard-codes a low temperature (0.2) for factual, conservative output. Do not change this lightly.
- **Audit logs**: Every session creates a file in `session_logs/`. Open it in any text editor. You can prove to yourself (and your conscience) that the model was only working with what you actually gave it.

## Recommended Workflow (Matches v2.1)

1. Initialize → Phase A (Compliance Matrix + gaps)
2. "Run Pink Team review on the current matrix and themes"
3. "Now execute Phase B fully, including lean cost strategy"
4. "Draft the executive summary / quad chart"
5. "Run full Red Team on the technical approach + cost narrative"
6. Iterate with Gold Team mindset ("What would a skeptical GS-14 at 7pm flag?")

## File Locations

- Master prompt: `capture/prompts/elite-capture-orchestrator-v2.md`
- This tool: `capture/ollama_capture_tool/main.py`
- Your ethics audit logs: `capture/ollama_capture_tool/session_logs/`

## Future Improvements You Can Make

- Document indexing / RAG-style retrieval so you don't have to send every full document on every turn
- Better PDF table extraction
- Simple Markdown-to-ODT export helper
- Per-document "send full / send summary only" toggles

This tool was built to protect your integrity while still giving you the full power of the agentic orchestrator prompt you helped design.

Use it honestly. Submit only what you can defend with evidence.
