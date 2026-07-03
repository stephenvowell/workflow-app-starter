"""Launcher - a desktop command center for your workflow app(s).

Register your tools in TOOLS below; each becomes a button. Clicking one runs
that tool with its output (and your yes/no answers) captured in an embedded
console - no popup terminals. Reuse this across clients; usually you only edit
TOOLS, the title, and maybe the palette.

Run:  python app/launcher.py
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
VENV_PY = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"

APP_TITLE = "Workflow Copilot"

# --- Register your tools here ----------------------------------------------
# emoji, label, script (in app/), extra CLI args, supports_demo
TOOLS = [
    ("\U0001F9E9", "Run Workflow", "workflow.py", (), True),
    # ("\U0001F4E7", "Email Check", "email_check.py", ("--no-popup",), False),
    # ("\U0001F4CA", "Daily Report", "report.py", (), True),
]

# --- Palette (dark navy + blue; swap to match a client's brand) -------------
BG = "#0d1528"
PANEL = "#122040"
PANEL2 = "#1a2d5c"
CONSOLE_BG = "#080e1c"
ACCENT = "#3b82f6"
ACCENT_H = "#2563eb"
ACCENT_L = "#93c5fd"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
DANGER = "#f87171"
DANGER_H = "#dc2626"
OK = "#4ade80"

FONT = "Segoe UI"
MONO = "Consolas"

_DONE = object()


def python_exe() -> str:
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def has_api_key() -> bool:
    if (os.environ.get("CURSOR_API_KEY") or "").strip():
        return True
    try:
        for line in (PROJECT_ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("CURSOR_API_KEY="):
                return line.split("=", 1)[1].strip() not in ("", "cursor_your_key_here")
    except OSError:
        pass
    return False


class Launcher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.configure(bg=BG)
        self.geometry("760x760")
        self.minsize(640, 660)

        self.demo = tk.BooleanVar(value=False)
        self.proc: subprocess.Popen | None = None
        self.out_q: queue.Queue = queue.Queue()
        self.run_buttons: list[tk.Button] = []
        self.current_tool = ""

        self._set_icon()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._drain_queue)

    def _set_icon(self) -> None:
        assets = PROJECT_ROOT / "assets"
        ico, png = assets / "copilot-icon.ico", assets / "copilot-icon.png"
        try:
            if ico.exists():
                self.iconbitmap(default=str(ico))
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            if png.exists():
                self._icon_img = tk.PhotoImage(file=str(png))
                self.iconphoto(True, self._icon_img)
        except Exception:  # noqa: BLE001
            pass

    def _btn(self, parent, text, command, *, base=ACCENT, hover=ACCENT_H,
             fg="#ffffff", font=(FONT, 10, "bold"), padx=12, pady=8, width=0):
        b = tk.Button(parent, text=text, command=command, bg=base, fg=fg,
                      activebackground=hover, activeforeground="#ffffff",
                      relief="flat", bd=0, cursor="hand2", font=font,
                      padx=padx, pady=pady, width=width)
        b.bind("<Enter>", lambda _e: b.configure(bg=hover) if str(b["state"]) != "disabled" else None)
        b.bind("<Leave>", lambda _e: b.configure(bg=base) if str(b["state"]) != "disabled" else None)
        return b

    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=22, pady=(18, 4))
        tk.Label(header, text=APP_TITLE, bg=BG, fg=TEXT,
                 font=(FONT, 22, "bold")).pack(side="left")
        self.status_lbl = tk.Label(header, text="idle", bg=BG, fg=MUTED,
                                   font=(FONT, 10, "italic"))
        self.status_lbl.pack(side="right")

        status = tk.Frame(self, bg=BG)
        status.pack(fill="x", padx=22, pady=(0, 8))
        self._chip(status, "API key", has_api_key())
        self._chip(status, "venv", VENV_PY.exists())

        tools = tk.Frame(self, bg=BG)
        tools.pack(fill="x", padx=22, pady=(0, 8))
        for emoji, label, script, extra, supports_demo in TOOLS:
            b = self._btn(
                tools, f"{emoji}  {label}",
                lambda s=script, x=extra, d=supports_demo: self._start_tool(s, x, d),
                base=PANEL, hover=PANEL2, fg=TEXT, font=(FONT, 10, "bold"),
            )
            b.pack(side="left", padx=(0, 8))
            self.run_buttons.append(b)

        tk.Checkbutton(
            tools, text="Demo mode", variable=self.demo, bg=BG, fg=MUTED,
            selectcolor=PANEL, activebackground=BG, activeforeground=ACCENT_L,
            font=(FONT, 9), bd=0, highlightthickness=0, cursor="hand2",
        ).pack(side="left", padx=(6, 0))

        con_wrap = tk.Frame(self, bg=ACCENT)
        con_wrap.pack(fill="both", expand=True, padx=22, pady=(0, 8))
        self.console = tk.Text(
            con_wrap, bg=CONSOLE_BG, fg=TEXT, insertbackground=ACCENT_L,
            font=(MONO, 10), relief="flat", bd=0, wrap="word", padx=12, pady=10,
            state="disabled", height=16,
        )
        self.console.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        sb = tk.Scrollbar(con_wrap, command=self.console.yview)
        sb.pack(side="right", fill="y")
        self.console.configure(yscrollcommand=sb.set)
        self.console.tag_configure("you", foreground=ACCENT_L)
        self.console.tag_configure("sys", foreground=MUTED, font=(MONO, 9, "italic"))
        self._log("Pick a tool above. Output shows here; answer prompts below "
                  "(or use Yes / No).\n", "sys")

        inp = tk.Frame(self, bg=BG)
        inp.pack(fill="x", padx=22, pady=(0, 16))
        self.entry = tk.Entry(inp, bg=PANEL, fg=TEXT, insertbackground=ACCENT_L,
                              relief="flat", font=(MONO, 10), disabledbackground=PANEL)
        self.entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        self.entry.bind("<Return>", lambda _e: self._send(self.entry.get()))
        self._btn(inp, "Send", lambda: self._send(self.entry.get()), padx=14).pack(side="left", padx=(0, 6))
        self._btn(inp, "Yes", lambda: self._send("y"), base=PANEL, hover=PANEL2, fg=OK, width=4).pack(side="left", padx=(0, 6))
        self._btn(inp, "No", lambda: self._send("n"), base=PANEL, hover=PANEL2, fg=DANGER, width=4).pack(side="left", padx=(0, 6))
        self.stop_btn = self._btn(inp, "Stop", self._stop, base=DANGER, hover=DANGER_H, width=5)
        self.stop_btn.pack(side="left", padx=(0, 6))
        self._btn(inp, "Clear", self._clear, base=PANEL, hover=PANEL2, fg=MUTED, width=5).pack(side="left")

        self._set_running(False)

    def _chip(self, parent, label, ok: bool) -> None:
        chip = tk.Frame(parent, bg=BG)
        chip.pack(side="left", padx=(0, 14))
        tk.Label(chip, text="\u25CF", bg=BG, fg=(OK if ok else DANGER), font=(FONT, 10)).pack(side="left")
        tk.Label(chip, text=f" {label}", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left")

    def _log(self, text: str, tag: str | None = None) -> None:
        self.console.configure(state="normal")
        self.console.insert("end", text, tag or ())
        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear(self) -> None:
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        for b in self.run_buttons:
            b.configure(state=("disabled" if running else "normal"),
                        bg=("#0f1830" if running else PANEL))
        self.entry.configure(state=("normal" if running else "disabled"))
        self.stop_btn.configure(state=("normal" if running else "disabled"))
        self.status_lbl.configure(
            text=(f"running: {self.current_tool}" if running else "idle"),
            fg=(OK if running else MUTED))
        if running:
            self.entry.focus_set()

    def _start_tool(self, script: str, extra: tuple, supports_demo: bool) -> None:
        if self.proc is not None:
            self._log("\n[a tool is already running - Stop it first]\n", "sys")
            return
        args = list(extra)
        if supports_demo and self.demo.get():
            args.append("--demo")

        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        cmd = [python_exe(), "-u", str(APP_DIR / script), *args]
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self._clear()
        self.current_tool = script
        self._log(f"$ {' '.join([Path(cmd[0]).name, *cmd[1:]])}\n\n", "sys")
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=str(PROJECT_ROOT), env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1, creationflags=no_window,
            )
        except Exception as exc:  # noqa: BLE001
            self._log(f"[failed to start: {exc}]\n", "sys")
            self.proc = None
            return
        self._set_running(True)
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout is not None
            while True:
                ch = proc.stdout.read(1)
                if ch == "":
                    break
                self.out_q.put(ch)
        except Exception:  # noqa: BLE001
            pass
        finally:
            proc.wait()
            self.out_q.put((_DONE, proc.returncode))

    def _drain_queue(self) -> None:
        chunks: list[str] = []
        done_code = None
        try:
            while True:
                item = self.out_q.get_nowait()
                if isinstance(item, tuple) and item and item[0] is _DONE:
                    done_code = item[1]
                    break
                chunks.append(item)
        except queue.Empty:
            pass
        if chunks:
            self._log("".join(chunks))
        if done_code is not None:
            self._log(f"\n\n[{self.current_tool} finished, exit code {done_code}]\n", "sys")
            self.proc = None
            self._set_running(False)
        self.after(50, self._drain_queue)

    def _send(self, text: str) -> None:
        if self.proc is None or self.proc.stdin is None:
            return
        try:
            self.proc.stdin.write(text + "\n")
            self.proc.stdin.flush()
            self._log(f"{text or '(enter)'}\n", "you")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[couldn't send input: {exc}]\n", "sys")
        self.entry.delete(0, "end")

    def _stop(self) -> None:
        if self.proc is not None:
            self._log("\n[stopping...]\n", "sys")
            try:
                self.proc.terminate()
            except Exception:  # noqa: BLE001
                pass

    def _on_close(self) -> None:
        self._stop()
        self.destroy()


def main() -> None:
    Launcher().mainloop()


if __name__ == "__main__":
    main()
