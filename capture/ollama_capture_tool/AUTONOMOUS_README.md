# Autonomous (Hands-Off) Capture Runner — v2.2 (Improved ISO Handling + Larger Fonts)

This is the tool you asked for.

**Goal:** Load your documents → click one button → go live your life → come back to a complete (or near-complete) proposal package.

## v2.2 Changes (Important)

- Much larger fonts throughout the entire interface (13pt base, bigger headers and logs) for better readability.
- No more hard-coded ISO folder paths (this was causing the "Folder Not Found" error).
- New **"Set ISO Folder..."** button so you only have to point to your certificates once.
- The chosen ISO location is now saved permanently in `iso_certs_config.json`.
- Improved auto-detection logic.

## How to Use (The "Coffee Run" Workflow)

1. **Start Ollama** and make sure your model is loaded.

2. Run the autonomous tool:
   ```bash
   cd /home/bob/Shadowbroker/capture/ollama_capture_tool
   python autonomous_runner.py
   ```

3. Enter the opportunity name.

4. Click the **"Auto-load ISO 9001 & 27001"** button.  
   If it can't find your folder, click **"Set ISO Folder..."** once and point it to:
   `/home/bob/Documents/PATL/Official Documents`

5. Click **"Add Documents"** for everything else (your real capability statements, tech summaries, past performance, etc.).

6. Click the big **"START AUTONOMOUS RUN"** button.

7. **Walk away.**

8. When you return, review the output carefully (this part is **not** automated).

## What Gets Saved

Every run creates a folder under `autonomous_runs/` containing:
- `full_audit_log.md` (complete ethics audit trail)
- The final assembled Markdown package

## Recommendation

Use this tool when you want to generate a strong first draft with minimal babysitting.  
Use `main.py` (the conversational version) later for refinement.

Run it honestly. Review ruthlessly.
