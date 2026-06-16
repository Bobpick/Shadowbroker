#!/usr/bin/env python3
"""
Ollama Capture Assistant — Ethical Proposal Support Tool (Conversational Version)
For use with Elite Capture Orchestrator v2.2

Larger fonts for readability.
Smart ISO certificate handling with saved location.
"""

import os
import json
import datetime
from pathlib import Path
from typing import List, Dict, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import ollama
except ImportError:
    ollama = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_MODEL = "cogito:70b"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"

MASTER_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "elite-capture-orchestrator-v2.md"

LOG_DIR = Path(__file__).parent / "session_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ISO Certificates Configuration
ISO_CONFIG_FILE = Path(__file__).parent / "iso_certs_config.json"
ISO_CERTS_KEYWORDS = ["ISO 9001", "ISO 27001", "ISO9001", "ISO27001"]

POSSIBLE_ISO_LOCATIONS = [
    Path.home() / "Documents" / "PATL" / "Official Documents",
    Path.home() / "Documents" / "Official Documents",
    Path("/home/bob/Documents/PATL/Official Documents"),
    Path("/home/workdir/Documents/PATL/Official Documents"),
]


def load_iso_certs_path() -> Path | None:
    if ISO_CONFIG_FILE.exists():
        try:
            data = json.loads(ISO_CONFIG_FILE.read_text())
            path = Path(data.get("iso_certs_path", ""))
            if path.exists():
                return path
        except Exception:
            pass
    return None


def save_iso_certs_path(path: Path):
    try:
        ISO_CONFIG_FILE.write_text(json.dumps({"iso_certs_path": str(path)}, indent=2))
    except Exception as e:
        print(f"Warning: Could not save ISO path: {e}")


def find_iso_certs_folder() -> Path | None:
    saved = load_iso_certs_path()
    if saved and saved.exists():
        return saved
    for candidate in POSSIBLE_ISO_LOCATIONS:
        if candidate.exists():
            save_iso_certs_path(candidate)
            return candidate
    return None


# =============================================================================
# DOCUMENT EXTRACTION
# =============================================================================

class DocumentExtractor:
    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown", ".rtf"}

    def __init__(self):
        self.missing_deps = []
        if PdfReader is None:
            self.missing_deps.append("pypdf")
        if Document is None:
            self.missing_deps.append("python-docx")

    def get_missing_dependencies(self):
        return self.missing_deps

    def extract_text(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_pdf(file_path)
        elif suffix == ".docx":
            return self._extract_docx(file_path)
        else:
            return file_path.read_text(encoding="utf-8", errors="replace")

    def _extract_pdf(self, path: Path) -> str:
        if PdfReader is None:
            raise RuntimeError("pypdf not installed")
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)

    def _extract_docx(self, path: Path) -> str:
        if Document is None:
            raise RuntimeError("python-docx not installed")
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


# =============================================================================
# PROMPT ASSEMBLER
# =============================================================================

class PromptAssembler:
    def __init__(self, master_prompt_path: Path):
        self.master_prompt = master_prompt_path.read_text(encoding="utf-8")

    def build_initial_system_message(self) -> str:
        ethics_block = """
================================================================================
ETHICAL GROUNDING RULES (MANDATORY)
================================================================================
You are assisting a highly ethical SDVOSB capture professional who refuses to 
cheat, exaggerate, or invent content.

STRICT REQUIREMENTS:
- You may ONLY use information that is explicitly present in the documents the 
  user has provided in THIS session.
- If a requirement cannot be met with the provided evidence, you MUST explicitly 
  state the gap.
- All TRL claims, maturity assertions, cost estimates, and capability statements 
  must be conservative and directly traceable.
- ISO 9001 and ISO 27001 certifications (when provided) are audited facts.
- Lean organizational reality is a constraint. Never propose approaches a small 
  team with limited B&P budget could not credibly deliver.

The user will always make the final decision on what is submitted.
================================================================================
"""
        return f"{self.master_prompt}\n\n{ethics_block}".strip()


# =============================================================================
# SESSION LOGGER
# =============================================================================

class SessionLogger:
    def __init__(self, opportunity_name: str):
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in opportunity_name)[:60]
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = LOG_DIR / f"{timestamp}_{safe_name}.md"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write(f"# Capture Session Log — {opportunity_name}\n")
            f.write(f"Started: {datetime.datetime.now().isoformat()}\n\n")
            f.write("**ETHICS NOTE**: This log contains every prompt sent to the model.\n\n---\n\n")

    def log_turn(self, turn_num: int, role: str, content: str, model: str = ""):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n## Turn {turn_num} — {role.upper()} ({model})\n")
            f.write(f"Timestamp: {datetime.datetime.now().isoformat()}\n\n")
            f.write("```\n")
            f.write(content[:12000] if len(content) > 12000 else content)
            if len(content) > 12000:
                f.write("\n[... truncated ...]\n")
            f.write("\n```\n")

    def get_log_path(self):
        return self.log_path


# =============================================================================
# MAIN APPLICATION
# =============================================================================

class EthicalCaptureAssistant:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Ethical Capture Assistant — Ollama (Conversational)")

        # Larger fonts
        self.base_font = ("DejaVu Sans", 13)
        self.header_font = ("DejaVu Sans", 14, "bold")
        self.mono_font = ("DejaVu Sans Mono", 12)

        self.root.option_add("*Font", self.base_font)
        self.root.geometry("1320x950")

        # Start maximized
        try:
            self.root.attributes('-zoomed', True)
        except Exception:
            self.root.update_idletasks()
            self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")

        self.extractor = DocumentExtractor()
        self.assembler = PromptAssembler(MASTER_PROMPT_PATH)
        self.logger: Optional[SessionLogger] = None
        self.conversation_history: List[Dict] = []
        self.documents: List[Dict] = []
        self.current_model = DEFAULT_MODEL

        self._build_ui()
        self._check_dependencies()

    def _check_dependencies(self):
        missing = self.extractor.get_missing_dependencies()
        if missing:
            messagebox.showwarning(
                "Missing Dependencies",
                "For best results install:\npip install pypdf python-docx ollama"
            )
        if ollama is None:
            messagebox.showerror(
                "Ollama Missing",
                "pip install ollama\n\nMake sure Ollama is running."
            )

    def _build_ui(self):
        # Ethics banner
        ethics_frame = ttk.LabelFrame(self.root, text="ETHICAL COMMITMENT", padding=10)
        ethics_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        ethics_text = (
            "This tool exists to support rigorous, honest proposal development only.\n"
            "• You MUST provide the actual documents.\n"
            "• Gaps and conservative assessments are features, not bugs.\n"
            "• Every prompt is logged for your personal audit.\n"
            "• You remain 100% responsible for what is submitted."
        )
        ttk.Label(ethics_frame, text=ethics_text, justify=tk.LEFT, foreground="#8B0000", font=self.base_font).pack(anchor=tk.W)

        # Main layout
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # LEFT SIDE
        left_frame = ttk.Frame(main_pane, width=420)
        main_pane.add(left_frame, weight=0)

        ttk.Label(left_frame, text="Opportunity Name:", font=self.header_font).pack(anchor=tk.W, pady=(5, 0))
        self.opp_name_var = tk.StringVar(value="New BAA / SBIR Opportunity")
        ttk.Entry(left_frame, textvariable=self.opp_name_var, width=50, font=self.base_font).pack(fill=tk.X, pady=2)

        ttk.Label(left_frame, text="Ollama Model:", font=self.header_font).pack(anchor=tk.W, pady=(8, 0))
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        ttk.Entry(left_frame, textvariable=self.model_var, width=30, font=self.base_font).pack(fill=tk.X)

        # Solicitation
        ttk.Label(left_frame, text="Solicitation:", font=self.header_font).pack(anchor=tk.W, pady=(12, 0))
        self.solicitation_path = tk.StringVar()
        ttk.Entry(left_frame, textvariable=self.solicitation_path, state="readonly", font=self.base_font).pack(fill=tk.X)
        ttk.Button(left_frame, text="Choose Solicitation File...", command=self._choose_solicitation).pack(anchor=tk.W, pady=2)

        # Supporting Documents
        ttk.Label(left_frame, text="Supporting Documents:", font=self.header_font).pack(anchor=tk.W, pady=(12, 0))

        doc_controls = ttk.Frame(left_frame)
        doc_controls.pack(fill=tk.X)
        ttk.Button(doc_controls, text="Add Documents...", command=self._add_supporting_docs).pack(side=tk.LEFT)
        ttk.Button(doc_controls, text="Auto-load ISO 9001 & 27001", command=self._auto_load_iso_certs).pack(side=tk.LEFT, padx=5)
        ttk.Button(doc_controls, text="Remove Selected", command=self._remove_selected_doc).pack(side=tk.LEFT, padx=5)

        self.doc_listbox = tk.Listbox(left_frame, height=13, selectmode=tk.SINGLE, exportselection=False, font=self.base_font)
        self.doc_listbox.pack(fill=tk.BOTH, expand=False, pady=4)

        ttk.Label(left_frame, text="Tip: Use 'Auto-load ISO 9001 & 27001' or configure via the Autonomous tool.", 
                  foreground="#006400", font=self.base_font).pack(anchor=tk.W, pady=(2, 4))

        # Action buttons
        action_frame = ttk.Frame(left_frame)
        action_frame.pack(fill=tk.X, pady=15)

        self.init_btn = ttk.Button(action_frame, text="INITIALIZE SESSION", command=self._initialize_session)
        self.init_btn.pack(fill=tk.X, pady=3)

        self.save_log_btn = ttk.Button(action_frame, text="Save Current Markdown Output", command=self._save_markdown, state=tk.DISABLED)
        self.save_log_btn.pack(fill=tk.X, pady=3)

        # RIGHT SIDE - Output
        right_frame = ttk.Frame(main_pane)
        main_pane.add(right_frame, weight=1)

        ttk.Label(right_frame, text="Conversation with Model", font=self.header_font).pack(anchor=tk.W)

        self.output_text = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, height=28, font=self.mono_font)
        self.output_text.pack(fill=tk.BOTH, expand=True, pady=4)

        # Follow-up
        input_frame = ttk.Frame(right_frame)
        input_frame.pack(fill=tk.X, pady=4)

        self.input_text = tk.Text(input_frame, height=5, wrap=tk.WORD, font=self.mono_font)
        self.input_text.pack(fill=tk.X, side=tk.LEFT, expand=True)
        self.input_text.bind("<Control-Return>", lambda e: self._send_followup())

        ttk.Button(input_frame, text="Send Follow-up\n(Ctrl+Enter)", command=self._send_followup).pack(side=tk.RIGHT, padx=6)

        # Status bar
        self.status_var = tk.StringVar(value="Ready. Load documents, then click 'INITIALIZE SESSION'.")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(fill=tk.X, side=tk.BOTTOM)

    # --- UI Actions ---
    def _choose_solicitation(self):
        path = filedialog.askopenfilename(
            title="Select Solicitation",
            initialdir=str(DEFAULT_DOCS_DIR)
        )
        if path:
            self.solicitation_path.set(path)
            if not any(d["path"] == path for d in self.documents):
                self._add_document_to_list(Path(path), "Solicitation")

    def _add_supporting_docs(self):
        paths = filedialog.askopenfilenames(
            title="Select Supporting Documents",
            initialdir=str(DEFAULT_DOCS_DIR)
        )
        for p in paths:
            self._add_document_to_list(Path(p), self.category_var.get() if hasattr(self, 'category_var') else "General")

    def _add_document_to_list(self, path: Path, category: str):
        if not path.exists():
            return
        if any(d["path"] == str(path) for d in self.documents):
            return

        doc_id = f"D{len(self.documents) + 1:02d}"
        self.documents.append({
            "id": doc_id,
            "path": str(path),
            "filename": path.name,
            "category": category,
            "size": path.stat().st_size,
            "content": None
        })
        self.doc_listbox.insert(tk.END, f"[{doc_id}] {path.name}  ({category})")

    def _remove_selected_doc(self):
        sel = self.doc_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.doc_listbox.delete(idx)
        del self.documents[idx]

    def _auto_load_iso_certs(self):
        iso_folder = find_iso_certs_folder()
        if not iso_folder or not iso_folder.exists():
            response = messagebox.askyesno("ISO Folder", "ISO folder not found. Select it manually?")
            if response:
                self._set_iso_folder()
            return

        loaded = []
        for pdf in sorted(iso_folder.glob("*.pdf")):
            if any(kw.lower() in pdf.name.lower() for kw in ISO_CERTS_KEYWORDS):
                if any(d["path"] == str(pdf) for d in self.documents):
                    continue
                doc_id = f"D{len(self.documents) + 1:02d}"
                self.documents.append({
                    "id": doc_id, "path": str(pdf), "filename": pdf.name,
                    "category": "ISO 9001/27001", "size": pdf.stat().st_size, "content": None
                })
                self.doc_listbox.insert(tk.END, f"[{doc_id}] {pdf.name}  (ISO 9001/27001)")
                loaded.append(pdf.name)

        if loaded:
            messagebox.showinfo("Loaded", "ISO certificates loaded:\n" + "\n".join(loaded))

    def _set_iso_folder(self):
        folder = filedialog.askdirectory(
            title="Select ISO Certificates Folder",
            initialdir=str(DEFAULT_DOCS_DIR)
        )
        if folder:
            save_iso_certs_path(Path(folder))
            messagebox.showinfo("Saved", f"ISO folder saved: {folder}")

    # --- Core Logic ---
    def _initialize_session(self):
        if not self.documents:
            messagebox.showwarning("No Documents", "Please add documents first.")
            return

        opp_name = self.opp_name_var.get().strip()
        self.current_model = self.model_var.get().strip() or DEFAULT_MODEL

        self.status_var.set("Extracting documents...")
        self.root.update()

        for doc in self.documents:
            if doc["content"] is None:
                doc["content"] = self.extractor.extract_text(Path(doc["path"]))

        self.logger = SessionLogger(opp_name)

        messages = []
        system_msg = self.assembler.build_initial_system_message()
        messages.append({"role": "system", "content": system_msg})

        inventory = "DOCUMENT INVENTORY:\n" + "\n".join(
            f"- [{d['id']}] {d['filename']} ({d['category']})" for d in self.documents
        )

        user_content = f"# NEW OPPORTUNITY: {opp_name}\n\n{inventory}\n\n--- FULL TEXTS ---\n"
        for d in self.documents:
            user_content += f"\n### [{d['id']}] {d['filename']}\n{d['content']}\n---\n"

        user_content += "\nPlease begin with Phase A (Compliance Matrix)."

        messages.append({"role": "user", "content": user_content})
        self.conversation_history = messages

        self.logger.log_turn(1, "system+user", user_content, self.current_model)

        self.status_var.set(f"Calling {self.current_model}...")
        self.root.update()

        try:
            response = self._call_ollama(messages)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        self.conversation_history.append({"role": "assistant", "content": response})
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, f"# {opp_name}\n\n{response}")

        self.logger.log_turn(2, "assistant", response, self.current_model)
        self.save_log_btn.config(state=tk.NORMAL)
        self.status_var.set("Session initialized.")

    def _send_followup(self):
        user_input = self.input_text.get("1.0", tk.END).strip()
        if not user_input or not self.conversation_history:
            return

        self.conversation_history.append({"role": "user", "content": user_input})
        self.input_text.delete("1.0", tk.END)

        self.status_var.set("Thinking...")
        self.root.update()

        try:
            response = self._call_ollama(self.conversation_history)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        self.conversation_history.append({"role": "assistant", "content": response})

        self.output_text.insert(tk.END, f"\n\n---\n\n**You:** {user_input}\n\n{response}")
        self.output_text.see(tk.END)

        if self.logger:
            turn = len(self.conversation_history)
            self.logger.log_turn(turn-1, "user", user_input)
            self.logger.log_turn(turn, "assistant", response, self.current_model)

        self.status_var.set("Follow-up complete.")

    def _call_ollama(self, messages):
        if ollama is None:
            raise RuntimeError("ollama package not installed")

        client = ollama.Client(host=DEFAULT_OLLAMA_HOST)
        resp = client.chat(
            model=self.current_model,
            messages=messages,
            options={"temperature": 0.2, "num_ctx": 32768}
        )
        return resp['message']['content']

    def _save_markdown(self):
        content = self.output_text.get("1.0", tk.END).strip()
        if not content:
            return
        default = f"{self.opp_name_var.get().strip().replace(' ', '_')}_output.md"
        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            initialfile=default,
            initialdir=str(DEFAULT_DOCS_DIR)
        )
        if path:
            Path(path).write_text(content, encoding="utf-8")
            self.status_var.set(f"Saved to {path}")


if __name__ == "__main__":
    root = tk.Tk()
    app = EthicalCaptureAssistant(root)
    root.mainloop()
