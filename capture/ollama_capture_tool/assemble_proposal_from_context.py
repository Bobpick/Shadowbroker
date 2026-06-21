#!/usr/bin/env python3
"""
assemble_proposal_from_context.py

Second program / recovery helper for the autonomous capture runner.

Purpose:
- Take a run directory (or direct proposal_context.json) from a previous autonomous run.
- "Take everything" available (the rich context JSON + audit log for salient requirements
  + foundation documents list + metadata).
- Produce the complete, stitched, professional proposal as final_proposal.md + .odt.

This is the tool for the situation where a run produced proposal_context.json
(and full_audit_log.md) but did not emit the final readable package, or you only
see the executive summary because you're looking at the raw JSON.

Usage (headless / overnight):
    python assemble_proposal_from_context.py --run-dir "/path/to/20260527_144307_New Opportunity"
    python assemble_proposal_from_context.py --context-json "/path/to/proposal_context.json"

The script is deliberately standalone (pure stdlib + the small basic ODT writer).
It does not import the giant autonomous_runner.py or pull in tkinter at module level.

All documents in ODT format (plus .md). No extra language.
"""

import os
import sys
import json
import argparse
import datetime
from pathlib import Path
from typing import Optional, Tuple


def _write_basic_odt(title: str, content: str, output_path: Path) -> None:
    """Basic ODT writer using only stdlib (zipfile). Produces a usable .odt with headings and paragraphs.
    This is the 'basic odt writer' — no external dependencies required.
    """
    import zipfile
    from xml.sax.saxutils import escape

    mimetype = b'application/vnd.oasis.opendocument.text'

    manifest = '''<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
 <manifest:file-entry manifest:media-type="application/vnd.oasis.opendocument.text" manifest:full-path="/"/>
 <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="content.xml"/>
 <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="styles.xml"/>
 <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="meta.xml"/>
</manifest:manifest>'''

    styles = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" office:version="1.2">
 <office:font-face-decls>
  <style:font-face style:name="Arial" svg:font-family="Arial" style:font-family-generic="swiss" style:font-pitch="variable"/>
 </office:font-face-decls>
 <office:styles>
  <style:style style:name="Standard" style:family="paragraph" style:class="text">
   <style:text-properties style:font-name="Arial" fo:font-size="12pt"/>
  </style:style>
  <style:style style:name="Heading 1" style:family="paragraph" style:parent-style-name="Standard" style:class="text">
   <style:text-properties style:font-name="Arial" fo:font-size="14pt" fo:font-weight="bold"/>
  </style:style>
  <style:style style:name="Heading 2" style:family="paragraph" style:parent-style-name="Standard" style:class="text">
   <style:text-properties style:font-name="Arial" fo:font-size="12pt" fo:font-weight="bold"/>
  </style:style>
 </office:styles>
</office:document-styles>'''

    meta = f'''<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" office:version="1.2">
 <office:meta>
  <dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">{escape(title)}</dc:title>
 </office:meta>
</office:document-meta>'''

    # Crude but usable markdown → ODT (## → heading 2, # → heading 1, rest → paragraphs)
    paragraphs = []
    for block in content.split('\n\n'):
        block = block.strip()
        if not block:
            continue
        if block.startswith('## '):
            h = escape(block[3:])
            paragraphs.append(f'<text:h text:outline-level="2">{h}</text:h>')
        elif block.startswith('# '):
            h = escape(block[2:])
            paragraphs.append(f'<text:h text:outline-level="1">{h}</text:h>')
        else:
            p = escape(block).replace('\n', '<text:line-break/>')
            paragraphs.append(f'<text:p>{p}</text:p>')

    content_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 office:version="1.2">
  <office:body>
    <office:text>
      <text:h text:outline-level="1">{escape(title)}</text:h>
      {''.join(paragraphs)}
    </office:text>
  </office:body>
</office:document-content>'''

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('mimetype', mimetype)
        z.writestr('META-INF/manifest.xml', manifest)
        z.writestr('content.xml', content_xml)
        z.writestr('styles.xml', styles)
        z.writestr('meta.xml', meta)

    print(f"[ODT] Basic ODT written to {output_path}")


def _extract_salient_from_audit_log(audit_path: Path) -> str:
    """Best-effort extraction of the Early Salient Requirements 5-section briefing
    from the full_audit_log.md. Returns the raw text block if found, else empty string.
    This lets the assembler "take everything" including the actionable initial box
    the operator saw in the Review dialog.
    """
    if not audit_path.exists():
        return ""

    try:
        text = audit_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

    # Look for the first occurrence of the salient output (the 5 sections)
    marker = "## KEY EVALUATION DRIVERS"
    idx = text.find(marker)
    if idx == -1:
        return ""

    # Grab a reasonable chunk after the marker (the 5 sections + a bit of context)
    chunk = text[idx: idx + 12000]  # generous but bounded
    # Stop at the next major MODEL CALL header or the end of the salient block
    stop_markers = ["\n## MODEL CALL", "\n# Agent Reference", "\n\n## "]
    for m in stop_markers:
        stop = chunk.find(m)
        if stop != -1:
            chunk = chunk[:stop]
            break

    return chunk.strip()


def build_final_proposal_markdown_from_context(context: dict, salient_text: str = "") -> str:
    """Build the complete stitched proposal markdown from a proposal_context.json dict.
    This is the "produce the proposal" logic. It takes everything available in the context
    plus an optional salient briefing extracted from the audit log.
    """
    meta = context.get("metadata", {})
    opp = meta.get("opportunity_name", "Unknown Opportunity")
    ts = meta.get("timestamp", datetime.datetime.now().isoformat())
    foundation_list = context.get("foundation_documents", [])
    docs = context.get("documents", [])
    cc = context.get("core_content", {})

    def get_md(key: str) -> str:
        entry = cc.get(key, {})
        if isinstance(entry, dict):
            return entry.get("markdown", "") or ""
        return str(entry) if entry else ""

    exec_sum = get_md("executive_summary")
    compliance = get_md("compliance_matrix")
    win = get_md("win_strategy")
    tech = get_md("technical_approach")
    past = get_md("past_performance")
    risk = get_md("risk_mitigation")
    visuals = get_md("visuals_concepts")

    # Build the document
    lines = []
    lines.append(f"# AUTONOMOUS CAPTURE PROPOSAL — {opp}")
    lines.append("")
    lines.append(f"**Generated from context:** {ts}")
    lines.append(f"**Model:** {meta.get('model', 'unknown')}")
    lines.append(f"**Run ID:** {meta.get('run_id', 'unknown')}")
    lines.append("")

    if foundation_list:
        lines.append("## Foundation Documents (Primary Technical Voice)")
        for f in foundation_list:
            lines.append(f"- {f}")
        lines.append("")

    if salient_text:
        lines.append("## Early Salient Requirements Extraction (Context from Solicitation)")
        lines.append(salient_text)
        lines.append("")
        lines.append("---")
        lines.append("")

    # Main body sections (order matches the lean 6-phase expectation)
    if exec_sum:
        lines.append("## 1. Executive Summary / Quad Chart Concept")
        lines.append(exec_sum)
        lines.append("")

    if compliance:
        lines.append("## 2. Living Compliance Matrix & Phase A")
        lines.append(compliance)
        lines.append("")

    if win:
        lines.append("## 3. Win Strategy, Cost & Lean Positioning (Phase B)")
        lines.append(win)
        lines.append("")

    if tech:
        lines.append("## 4. Technical Approach")
        lines.append(tech)
        lines.append("")

    if past:
        lines.append("## 5. Tailored Past Performance & Capabilities")
        lines.append(past)
        lines.append("")

    if risk:
        lines.append("## 6. Risk, Opportunity & Mitigation")
        lines.append(risk)
        lines.append("")

    if visuals:
        lines.append("## 7. Visual & Graphics Strategy")
        lines.append(visuals)
        lines.append("")

    # Footer note
    lines.append("---")
    lines.append("")
    lines.append("**End of Assembled Proposal**")
    lines.append("")
    lines.append("This document was recovered / assembled from `proposal_context.json` (and audit log where available).")
    lines.append("All claims are grounded in the documents loaded for this specific run only.")
    if docs:
        lines.append(f"Documents referenced: {len(docs)} total (see proposal_context.json for details).")

    return "\n".join(lines)


def write_proposal_package(context: dict, output_dir: Path, opportunity_name: Optional[str] = None, salient_text: str = "") -> Tuple[Path, Path]:
    """Write final_proposal.md + .odt into output_dir from the given context dict.
    Returns (md_path, odt_path).
    """
    opp = opportunity_name or context.get("metadata", {}).get("opportunity_name", "Proposal")
    md = build_final_proposal_markdown_from_context(context, salient_text)

    md_path = output_dir / "final_proposal.md"
    odt_path = output_dir / "final_proposal.odt"

    md_path.write_text(md, encoding="utf-8")
    _write_basic_odt(opp, md, odt_path)

    print(f"[Assembler] Wrote full proposal package:")
    print(f"  {md_path}")
    print(f"  {odt_path}")
    return md_path, odt_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assemble / recover the full proposal (MD + ODT) from a prior autonomous run's proposal_context.json and audit log."
    )
    parser.add_argument("--run-dir", type=str, default=None,
                        help="Path to a run directory containing proposal_context.json (and optionally full_audit_log.md).")
    parser.add_argument("--context-json", type=str, default=None,
                        help="Direct path to a proposal_context.json file.")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Where to write final_proposal.md + .odt (defaults to the run dir or the directory containing the JSON).")
    parser.add_argument("--opportunity-name", type=str, default=None,
                        help="Override opportunity name for the output files.")

    args = parser.parse_args()

    # Resolve the context JSON path
    context_path: Optional[Path] = None
    run_dir: Optional[Path] = None

    if args.context_json:
        context_path = Path(args.context_json).expanduser().resolve()
        run_dir = context_path.parent
    elif args.run_dir:
        run_dir = Path(args.run_dir).expanduser().resolve()
        candidate = run_dir / "proposal_context.json"
        if candidate.exists():
            context_path = candidate
        else:
            print(f"ERROR: proposal_context.json not found in {run_dir}")
            return 2
    else:
        # No args — try to be helpful but stay headless-friendly.
        # Only attempt a tiny Tk picker if a display is likely present and the user is interactive.
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            picked = filedialog.askopenfilename(
                title="Select proposal_context.json (or Cancel for CLI help)",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )
            root.destroy()
            if picked:
                context_path = Path(picked).resolve()
                run_dir = context_path.parent
            else:
                parser.print_help()
                return 0
        except Exception:
            parser.print_help()
            print("\nRun with --run-dir or --context-json (see above).")
            return 0

    if not context_path or not context_path.exists():
        print("ERROR: Could not locate proposal_context.json")
        return 2

    # Load the context
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Failed to load {context_path}: {e}")
        return 3

    # Determine output location
    out_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else (run_dir or context_path.parent)
    out_dir.mkdir(parents=True, exist_ok=True)

    # "Take everything" — try to pull the salient briefing from the audit log in the same directory
    audit_path = (run_dir or context_path.parent) / "full_audit_log.md"
    salient = _extract_salient_from_audit_log(audit_path)

    opp_name = args.opportunity_name or context.get("metadata", {}).get("opportunity_name")

    print(f"[Assembler] Loading context from {context_path}")
    if salient:
        print("[Assembler] Found Early Salient Requirements text in audit log — including it.")
    else:
        print("[Assembler] No salient text found in audit log (or no audit log present).")

    write_proposal_package(context, out_dir, opp_name, salient)
    print(f"\nDone. Full proposal is in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
