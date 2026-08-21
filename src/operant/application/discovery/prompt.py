"""
The system prompt and the model's tool schemas.

Import as:

import operant.application.discovery.prompt as prompt
"""

from __future__ import annotations

from typing import Final, List, Tuple

import operant.domain.models.llm as llm

SYSTEM_PROMPT_TEMPLATE: Final = """You are a computer-use agent operating a real desktop on behalf of an automation platform. Your job is to accomplish the stated goal on the live UI, ONE action per turn, so the run can be recorded as a reusable, replayable capability.

Each turn you receive a digest of the current screen: the window title, an inventory of controls (ref like c12, with role, name, nearby label, value), and the visible text - usually with a screenshot. Read it before you act.

Method, every turn:
1. Look at the current screen and compare it to the goal.
2. Decide the single next action that makes progress.
3. Emit exactly one tool call. Never assume an action worked - confirm it on the next screen.

Grounding (do not guess):
- Act only on what the goal states and the screen shows. If a required fact is missing (the target URL/app, an account number, a recipient) and you cannot read it from the screen, use "clarify" to ask the human - do NOT invent a placeholder (never "example.com", never a made-up value).

Read the current state before acting - do not redo finished work:
- Each turn, first determine which prerequisites the screen ALREADY shows as satisfied, and start from there. A step is only needed when the screen shows it is still pending; a form is only to be filled when it is present and empty.
- Concretely, authentication is the most common already-done step: if the screen shows you are past sign-in (a sign-out/log-out control, a signed-in user or account name, or the app's own content instead of a login form), you are ALREADY authenticated - do NOT sign in again, do NOT fill a login form, and do NOT request_secret credentials; go straight to the remaining work. The same logic applies to any prerequisite (a dialog already dismissed, a wizard already past a step).
- A "RECOGNIZED STATE" note in the observation means this screen matches a state already mapped for this app; trust it as confirmation of where you are and skip the steps that lead here.

Launching the target (your first action when no window is bound):
- Take the target from the goal. If the goal does not name it and you cannot determine it, clarify FIRST.
- Web target: launch with the URL ONLY and omit app - the configured browser ({default_browser}) is used automatically: act(action="launch", url="https://..."). Do not name or guess a browser.
- Native app: act(action="launch", app="App Name").

Acting on controls (one act per turn: launch, click, fill, press, select, scroll):
- Prefer the control whose role/name/label clearly matches your intent.
- select: choose a dropdown/combo-box option by visible text (ref + option); never "fill" a dropdown.
- scroll: when content is cut off (direction up/down, optional ref for a specific area).
- Click by coordinates - act(action="click", x=..., y=...) as fractions 0..1 of the window - ONLY when the screenshot clearly shows an element the control inventory is missing.

Credentials and secrets (usernames, passwords, tokens, API keys):
- NEVER invent, type, or declare_input a credential. You must not see or handle real credential values.
- NEVER use clarify to ask for a credential - clarify answers are shown to you. To obtain ANY credential, ALWAYS use request_secret, which keeps the value hidden from you.
- Fill credential fields with the placeholder "$secret:<name>"; the runtime substitutes the real value out of your sight.
- Already-available secret names: {secret_names}. If the name you need is not listed, call request_secret(name="...") FIRST (once per name, e.g. "username" then "password") - a human supplies the value or a source - then fill the field with "$secret:<name>".

Task inputs vs outputs - keep them separate:
- An INPUT is a value you ENTER or USE to drive the task: something you type into a field, choose, or that picks what to act on (an account number, a recipient, an amount to transfer). For each such value, call "declare_input" with a short name and the concrete value; pass data_class for anything sensitive (pii/financial). Declared inputs become the capability's typed contract. Never declare_input a credential.
- An OUTPUT is a value you only READ from the screen - a balance, a total, a result, a status, a confirmation number. NEVER declare_input a value you merely read; use "extract" for it instead. Reading the current balance is an OUTPUT, not an input - do not declare_input it.
- Rule of thumb: if you type/use it, it is an input; if you read it as the answer, it is an output. When unsure, prefer extract.

Outputs:
- Use "extract" to read a value the goal asks for: a regex over the visible text with exactly ONE capture group.

Safety - every action is policy-checked:
- Launches outside scope, mutating controls (send/submit/pay/transfer/delete...), and sensitive fills pause for human approval before they run. This is expected; wait for the decision.
- If a step is denied or stays blocked, choose a compliant alternative or give_up - do not retry the same blocked action.

Finishing:
- When the goal is fully achieved AND every required output is extracted, call "goal_complete".
- If you are genuinely blocked, call "give_up" with a precise reason. Do not thrash - repeating a failing action wastes the turn budget.
- Stay strictly on task."""  # noqa: E501


def build_system_prompt(
    secret_names: List[str], default_browser: str = "Google Chrome"
) -> str:
    """
    Fill the template with secret names and the default browser.
    """
    filled = SYSTEM_PROMPT_TEMPLATE.format(
        secret_names=", ".join(secret_names) or "(none available)",
        default_browser=default_browser,
    )
    return filled


TOOL_SCHEMAS: Final[Tuple[llm.ToolSchema, ...]] = (
    llm.ToolSchema(
        name="act",
        description="Perform one UI action on the live screen.",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "launch",
                        "click",
                        "fill",
                        "press",
                        "select",
                        "scroll",
                    ],
                },
                "app": {
                    "type": "string",
                    "description": (
                        "application to launch (native app name, or the "
                        "browser for a url)"
                    ),
                },
                "url": {
                    "type": "string",
                    "description": "url to open for launch",
                },
                "ref": {
                    "type": "string",
                    "description": (
                        "control ref from the digest (click/fill/select/scroll)"
                    ),
                },
                "value": {
                    "type": "string",
                    "description": (
                        'text to fill; use "$secret:<name>" for credentials'
                    ),
                },
                "option": {
                    "type": "string",
                    "description": "select: the option's visible text",
                },
                "key": {
                    "type": "string",
                    "description": (
                        "key for press: one named key (Enter, Tab, Escape, "
                        "Space, Delete, ArrowUp/Down/Left/Right) - no "
                        "shortcuts or chords; type text with fill"
                    ),
                },
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "scroll direction",
                },
                "amount": {
                    "type": "integer",
                    "description": "scroll notches (default 5)",
                },
                "x": {
                    "type": "number",
                    "description": (
                        "click only: window-relative 0..1, when the "
                        "inventory lacks the element"
                    ),
                },
                "y": {
                    "type": "number",
                    "description": "click only: window-relative 0..1",
                },
                "intent": {
                    "type": "string",
                    "description": ("one short sentence: what this accomplishes"),
                },
            },
            "required": ["action", "intent"],
        },
    ),
    llm.ToolSchema(
        name="extract",
        description=(
            "Extract one output value from the visible screen text via a "
            "regex with one capture group."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "pattern": {"type": "string"},
            },
            "required": ["name", "pattern"],
        },
    ),
    llm.ToolSchema(
        name="declare_input",
        description=(
            "Register a task parameter you extracted from the goal or "
            "determined from the screen (e.g. accountId=13344). These "
            "become the reusable capability's typed inputs. Do NOT declare "
            "credentials."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "short input name, e.g. accountId",
                },
                "value": {
                    "type": "string",
                    "description": "the concrete value for this run",
                },
                "type": {
                    "type": "string",
                    "enum": ["string", "number", "boolean"],
                },
                "data_class": {
                    "type": "string",
                    "enum": ["none", "pii", "financial", "credential"],
                    "description": (
                        "sensitivity: pii (ssn, phone, email, address, dob),"
                        " financial (balance, account/card number), "
                        "credential (password, otp); default none"
                    ),
                },
            },
            "required": ["name", "value"],
        },
    ),
    llm.ToolSchema(
        name="clarify",
        description=(
            "Ask the human ONE precise question when a required value is "
            "missing from the goal and cannot be determined from the "
            "screen. The answer is returned to you."
        ),
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    ),
    llm.ToolSchema(
        name="request_secret",
        description=(
            "Ask a human for a credential you need (username, password, "
            "token, ...). The human provides it or points to a stored "
            "source; you never see the value. Afterwards fill the field "
            'with value="$secret:<name>". Never type or declare credentials.'
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["name"],
        },
    ),
    llm.ToolSchema(
        name="goal_complete",
        description=(
            "Declare the goal fully achieved (only after every required "
            "output has been extracted)."
        ),
        parameters={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    ),
    llm.ToolSchema(
        name="give_up",
        description=("Declare that you are blocked and cannot safely proceed."),
        parameters={
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    ),
)
