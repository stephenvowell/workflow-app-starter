"""Reusable spine for agent-backed workflow apps.

Clone this folder per client/workflow. Everything a small workflow app needs
is here so each new project is "fill in the steps + prompts", not "start over":

  * config           - MODEL, paths, API-key loading (.env)
  * human-in-the-loop - approve() gate; nothing runs without a yes
  * output           - save_output() drops approved results in workspace/output/
  * streaming        - stream_text() shows the agent working, returns the text
  * demo mode        - --demo runs offline (no key, no cost) for client demos
  * workflow engine  - WorkflowStep + run_workflow(): define steps, get gating,
                       streaming, context passing, and saving for free
  * Windows fix      - shim for the cursor-sdk sync local bridge on Windows

The design rule (keep it): the agent DRAFTS, the human DECIDES.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Load CURSOR_API_KEY (and friends) from a local .env if python-dotenv exists.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

MODEL = os.environ.get("WORKFLOW_MODEL", "composer-2.5").strip() or "composer-2.5"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = PROJECT_ROOT / "workspace"      # agents run against this sandbox
OUTPUT_DIR = WORKSPACE / "output"           # approved results land here


# --- config / io ------------------------------------------------------------
def require_api_key() -> str:
    key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    if not key:
        print(
            "\nCURSOR_API_KEY is not set.\n"
            "  1. Create a key: https://cursor.com/dashboard/integrations\n"
            "  2. Copy .env.example to .env and paste it in, or set it now:\n"
            '       $env:CURSOR_API_KEY = "cursor_..."   (PowerShell)\n',
            file=sys.stderr,
        )
        raise SystemExit(1)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    return key


def rule(char: str = "-", width: int = 66) -> None:
    print(char * width)


def banner(title: str) -> None:
    rule("=")
    print(title)
    rule("=")


def approve(action: str, *, default_yes: bool = False) -> bool:
    """Ask before doing anything. Returns True only if approved."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        answer = input(f"\n>> {action}\n   Proceed? {suffix} ").strip().lower()
    except EOFError:
        return False
    if not answer:
        return default_yes
    return answer in ("y", "yes")


def ask_text(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def save_output(name: str, text: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(text, encoding="utf-8")
    return path


def stream_text(run) -> str:
    """Print an agent's assistant text as it streams; return the full text."""
    chunks: list[str] = []
    for message in run.messages():
        if getattr(message, "type", None) == "assistant":
            for block in message.message.content:
                if getattr(block, "type", None) == "text":
                    print(block.text, end="", flush=True)
                    chunks.append(block.text)
    run.wait()  # terminal result + releases the run's watchers
    print()
    return "".join(chunks)


# --- agent factory ----------------------------------------------------------
def new_agent(api_key: str):
    """A fresh local agent (or a fake one in demo mode). Imports the SDK lazily
    so the launcher/demo works even before cursor-sdk is installed."""
    if api_key == "demo":
        return FakeAgent()
    from cursor_sdk import Agent, LocalAgentOptions

    return Agent.create(
        model=MODEL, api_key=api_key, local=LocalAgentOptions(cwd=str(WORKSPACE))
    )


# --- workflow engine --------------------------------------------------------
@dataclass
class WorkflowStep:
    """One agent turn in a workflow.

    name:    shown in the approval prompt and used as the context key.
    prompt:  the text sent to the agent - a string, or a function of the
             running context dict (so later steps can use earlier results).
    save_as: optional output filename (string or function of context+text).
    gate:    require approval before running this step (default True).
    """

    name: str
    prompt: "str | Callable[[dict], str]"
    save_as: "str | Callable[[dict, str], str] | None" = None
    gate: bool = True


def run_workflow(steps: list[WorkflowStep], *, title: str,
                 api_key: str | None = None, demo: bool | None = None) -> dict:
    """Run a list of WorkflowSteps against one agent, gating each step.

    Returns a context dict {step_name: agent_output}. One agent is reused
    across steps, so each step sees the whole conversation.
    """
    demo = demo_enabled() if demo is None else demo
    api_key = "demo" if demo else (api_key or require_api_key())
    banner(title + ("  [DEMO]" if demo else ""))

    context: dict[str, str] = {}
    try:
        with new_agent(api_key) as agent:
            for i, step in enumerate(steps, start=1):
                if step.gate and not approve(
                    f"Step {i}/{len(steps)}: {step.name}", default_yes=True
                ):
                    print("   skipped.")
                    continue
                prompt = step.prompt(context) if callable(step.prompt) else step.prompt
                print(f"\n--- {step.name} ---")
                text = stream_text(agent.send(prompt))
                context[step.name] = text
                if step.save_as:
                    fname = (step.save_as(context, text)
                             if callable(step.save_as) else step.save_as)
                    path = save_output(fname, text)
                    print(f"   saved -> {path}")
        print(f"\nDone. Results in {OUTPUT_DIR}.")
    except KeyboardInterrupt:
        print("\nInterrupted. Nothing further was sent.")
    return context


# --- demo mode (offline, no key, no cost) -----------------------------------
import time as _time  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def demo_enabled() -> bool:
    if "--demo" in sys.argv:
        return True
    return os.environ.get("WORKFLOW_DEMO", "").strip().lower() in ("1", "true", "yes")


def _canned_reply(prompt: str) -> str:
    p = prompt.lower()
    if any(k in p for k in ("plan", "steps", "task list", "outline")):
        return ("1. Gather the inputs\n2. Do the core work\n3. Review and hand off")
    if any(k in p for k in ("review", "summarize", "verdict", "feedback", "wrap")):
        return ("- Solid structure and clear intent\n- Tighten a couple of lines\n"
                "- Ready to send after a quick proofread")
    return ("[demo draft] Your real agent output would appear here. Add "
            "CURSOR_API_KEY and drop --demo for live results.")


class _FakeRun:
    def __init__(self, text: str):
        self.run_id = "demo-run"
        self._text = text

    def text(self) -> str:
        return self._text

    def wait(self):
        return SimpleNamespace(status="finished", result=self._text, id=self.run_id)

    def messages(self):
        for piece in self._text.splitlines(keepends=True):
            _time.sleep(0.02)
            block = SimpleNamespace(type="text", text=piece)
            yield SimpleNamespace(type="assistant",
                                  message=SimpleNamespace(content=[block]))

    stream = messages


class FakeAgent:
    """Offline stand-in that quacks like an SDK agent."""

    def __init__(self):
        self.agent_id = "demo-agent"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def send(self, prompt: str) -> "_FakeRun":
        return _FakeRun(_canned_reply(prompt))

    def close(self):
        pass


def demo_prompt(message: str):
    return SimpleNamespace(status="finished", result=_canned_reply(message), id="demo-run")


# --- Windows compatibility shim ---------------------------------------------
# cursor-sdk's sync local bridge reads the bridge subprocess's stderr with
# select(), which on Windows only works on sockets. Swap in a thread-based
# reader. No-op on macOS/Linux, and harmless if the SDK isn't installed.
def _patch_sync_bridge_for_windows() -> None:
    if os.name != "nt":
        return
    try:
        import threading
        import time as _t

        from cursor_sdk import _bridge as _b
    except Exception:  # pragma: no cover
        return

    if getattr(_b, "_read_discovery_patched", False):
        return

    def _read_discovery(process, timeout):
        result: dict = {}
        lines: list[str] = []

        def reader():
            try:
                assert process.stderr is not None
                for raw in process.stderr:
                    lines.append(raw)
                    parsed = _b.parse_discovery_line(raw)
                    if parsed is not None:
                        result["discovery"] = parsed
                        return
            except Exception as exc:  # noqa: BLE001
                result["error"] = exc

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        deadline = _t.monotonic() + timeout
        while _t.monotonic() < deadline:
            if "discovery" in result:
                return result["discovery"]
            if "error" in result:
                raise _b.CursorSDKError(f"Bridge discovery read error: {result['error']}")
            if process.poll() is not None and not t.is_alive():
                raise _b.CursorSDKError(
                    f"Bridge exited before discovery with status {process.returncode}: "
                    + "".join(lines)
                )
            t.join(timeout=0.1)
        raise _b.CursorSDKError("Timed out waiting for bridge discovery")

    _b._read_discovery = _read_discovery
    _b._read_discovery_patched = True


_patch_sync_bridge_for_windows()
