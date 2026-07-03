"""YOUR WORKFLOW - fill in the blanks.

This is the one file you rewrite per client. Define what the workflow is, ask
for whatever inputs it needs, and list the steps. The engine (shared/) gives
you human approval on every step, live streaming, context passing between
steps, saving, and a --demo mode for free.

Mental model: each WorkflowStep is one agent turn. Later steps can read the
output of earlier steps via the `context` dict (keyed by step name).

The example below is a generic "weekly status report" workflow. Replace the
title, inputs, and steps with the client's actual process.

Run:  python app/workflow.py
      python app/workflow.py --demo     (offline, no API key, no cost)
"""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import WorkflowStep, ask_text, demo_enabled, run_workflow  # noqa: E402

# 1) NAME THE WORKFLOW ------------------------------------------------------
WORKFLOW_TITLE = "Weekly Status Report"


# 2) GATHER INPUTS ----------------------------------------------------------
# Ask the human for anything the workflow needs. Return a dict; it's merged
# into the step context so your prompts can reference it.
def gather_inputs() -> dict:
    if demo_enabled():
        return {"team": "Platform", "wins": "shipped the billing API; cut build time 40%"}
    team = ask_text("Team / area this report is for?\n> ") or "our team"
    wins = ask_text("This week's wins / progress (comma-separated)?\n> ") or "steady progress"
    return {"team": team, "wins": wins}


# 3) DEFINE THE STEPS -------------------------------------------------------
# Each step's prompt can be a plain string, or a function of the context dict
# (which holds your inputs plus every prior step's output).
def build_steps(inputs: dict) -> list[WorkflowStep]:
    return [
        WorkflowStep(
            name="Outline",
            prompt=(
                f"You are drafting a weekly status report for the {inputs['team']} "
                f"team. This week's raw notes: {inputs['wins']}.\n"
                "Propose a tight outline (3-5 sections) for a clear, exec-friendly "
                "report. Return just the outline."
            ),
        ),
        WorkflowStep(
            name="Draft",
            prompt=lambda ctx: (
                "Write the full weekly status report following this outline:\n"
                f"{ctx['Outline']}\n\n"
                f"Team: {inputs['team']}. Keep it concise, concrete, and honest. "
                "Use short paragraphs and bullet points where useful."
            ),
        ),
        WorkflowStep(
            name="Polish",
            prompt=lambda ctx: (
                "Tighten and proofread this report - fix wordiness, keep the "
                "meaning, make it skimmable. Return the final version only:\n\n"
                f"{ctx['Draft']}"
            ),
            # Save the final result. Filename can be a string or a function.
            save_as=lambda ctx, text: f"weekly-report-{date.today().isoformat()}.md",
        ),
    ]


def main() -> None:
    inputs = gather_inputs()
    steps = build_steps(inputs)
    run_workflow(steps, title=WORKFLOW_TITLE)


if __name__ == "__main__":
    main()
