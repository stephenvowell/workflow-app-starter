# Workflow App Starter

A reusable template for building **agent-backed workflow apps** for a client or
team. Clone it, define the workflow, wire in their systems, and hand over a
desktop app a non-coder can actually use.

Built on the [Cursor SDK](https://cursor.com/docs/sdk/python). The design rule:
**the agent drafts, the human decides** — every step is gated by approval.

## What you get

```
workflow-app-starter/
  shared/__init__.py   # the spine: config, approve(), streaming, saving,
                       #   demo mode, a workflow engine, and a Windows SDK fix
  app/workflow.py      # <- the one file you rewrite per client (steps + prompts)
  app/launcher.py      # a desktop GUI; runs your tools in an embedded console
  .env.example         # copy to .env, paste your CURSOR_API_KEY
  requirements.txt     # cursor-sdk + optional per-workflow integrations
```

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt
copy .env.example .env            # then paste your CURSOR_API_KEY

python app/workflow.py --demo     # try the example offline (no key, no cost)
python app/workflow.py            # run for real
python app/launcher.py            # the desktop command center
```

## Build a workflow in 4 moves (`app/workflow.py`)

1. **Name it** — set `WORKFLOW_TITLE`.
2. **Gather inputs** — edit `gather_inputs()` to ask for what the workflow needs.
3. **Define steps** — each `WorkflowStep` is one agent turn. Prompts can be a
   string or a function of the running `context` (so a step can use earlier
   outputs). Set `save_as` to write a result to `workspace/output/`.
4. **Run it** — `run_workflow(steps, title=...)` handles approval, streaming,
   context passing, and saving.

Register tools as buttons in `app/launcher.py` via the `TOOLS` list.

## Client intake checklist

Turn "what a business does" into an app by answering these with the client:

- [ ] **Trigger** — when does this run? (on demand / daily / on an event)
- [ ] **Inputs** — what does it need to start? (a date, an inbox, a spreadsheet)
- [ ] **Steps** — what are the 2-6 discrete stages a person does today?
- [ ] **Systems** — what does it read/write? (Gmail, a CRM, a DB, files) → these
      become API integrations or **MCP servers**
- [ ] **Approval points** — where must a human say yes before proceeding?
- [ ] **Output** — what's the deliverable, and where does it go?
- [ ] **Guardrails** — what must the agent NEVER do? what needs an audit trail?

Map inputs → `gather_inputs()`, stages → `WorkflowStep`s, systems → `tools/` +
`mcp_servers`, approval points → `gate=True`, output → `save_as`.

## Adding a company system (MCP)

Give the agent real tools by passing MCP servers when you create the agent
(see `shared/new_agent`). Example (stdio server):

```python
from cursor_sdk import AgentOptions, LocalAgentOptions, StdioMcpServerConfig
options = AgentOptions(
    api_key=api_key, model=MODEL,
    local=LocalAgentOptions(cwd=str(WORKSPACE)),
    mcp_servers={
        "crm": StdioMcpServerConfig(command="npx.cmd", args=["-y", "<their-mcp-server>"]),
    },
)
```

On Windows the stdio command must be `npx.cmd`, not `npx`.

## Ship it

- **Local run:** `python app/launcher.py`.
- **One-click .exe (personal / same-machine):**
  ```bash
  pip install pyinstaller
  pyinstaller --onefile --windowed --name workflow-copilot app/launcher.py
  ```
  Note: a frozen `.exe` still needs **Node.js** on the machine (the SDK spawns a
  Node bridge) and a `CURSOR_API_KEY` — never embed the key in the exe.

## Safety

`.env`, `credentials.json`, and `token.json` are gitignored. Keep the approval
gate on for anything that touches a client's real systems.
