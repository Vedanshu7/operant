"""
Replay robustness under UI changes: perturb recorded screens and check what
replay's two deterministic decisions do with them.

Replay uses no model, so this suite costs nothing. For every named
control on a few realistic screens it builds the strategy stack the
recorder would save (``recdng.strategies_for``), applies one UI
change, and resolves the stack on the changed screen:

- correct: the same control (controls keep their ``ref`` as identity
  here; live refs are ephemeral and resolution never reads them);
- wrong: a different control - replay would act on the wrong thing;
- escalated: nothing or several matched - replay stops for a person.

It also checks screen recognition: which recorded screen
``localize.locate`` names for each changed screen, and, for a sweep of
thresholds, which one fingerprint coverage alone would pick.

Import as:

import tests.evals.perturb as evpertur
"""

from __future__ import annotations

import dataclasses
import random
import re
from typing import Callable, Dict, List, Sequence, Tuple

import operant.application.recorder.recording as recdng
import operant.domain.fingerprint as odfinger
import operant.domain.graph.localize as localize
import operant.domain.locate as locate
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph

Screen = digest.ScreenDigest
Operator = Callable[[Screen, random.Random], Screen]

_INTERACTIVE = frozenset({"link", "button", "text_field", "combo_box"})
# Recognition thresholds compared against localize's _MIN_COVERAGE.
THRESHOLDS: Tuple[float, ...] = (0.4, 0.5, 0.6, 0.7, 0.8)
_WORDS = {
    "accounts overview": "Kontenübersicht",
    "transfer funds": "Überweisung",
    "bill pay": "Rechnungen",
    "find transactions": "Umsätze suchen",
    "update contact info": "Kontaktdaten",
    "log out": "Abmelden",
    "log in": "Anmelden",
    "username": "Benutzername",
    "password": "Passwort",
    "amount": "Betrag",
    "from account": "Von Konto",
    "to account": "Auf Konto",
    "transfer": "Überweisen",
    "account": "Konto",
    "balance": "Saldo",
}


# #############################################################################
# Screens
# #############################################################################


def _control(
    ref: str,
    role: str,
    name: str,
    path: str,
    box: Tuple[float, float, float, float],
    label: str = "",
) -> digest.Control:
    return digest.Control(
        ref=ref,
        role=role,
        name=name,
        label=label,
        path=path,
        box=digest.Box(*box),
    )


def _nav(prefix: str) -> List[digest.Control]:
    items = [
        "Accounts Overview",
        "Transfer Funds",
        "Bill Pay",
        "Find Transactions",
        "Update Contact Info",
        "Log Out",
    ]
    return [
        _control(
            f"nav{i}",
            "link",
            name,
            f"{prefix}>list:0>group:{i}>link:0",
            (0.2, 0.30 + 0.03 * i, 0.10, 0.02),
        )
        for i, name in enumerate(items)
    ]


def accounts_screen() -> Screen:
    """
    Build a list page: navigation, and a table of account links.
    """
    table = "content>group:0>group:2>table:0"
    rows = [("12345", "-$2300.00"), ("12456", "$10.45"), ("13344", "$1231.10")]
    controls = _nav("content>group:0>group:1")
    for i, (number, balance) in enumerate(rows):
        controls.append(
            _control(
                f"row{number}",
                "link",
                number,
                f"{table}>table_row:{i + 1}>table_cell:0>link:0",
                (0.45, 0.45 + 0.03 * i, 0.05, 0.02),
                label=balance,
            )
        )
    text = "Accounts Overview Account Balance* " + " ".join(
        f"{n} {b}" for n, b in rows
    )
    return Screen(
        app="Browser",
        window_title="Bank | Accounts Overview",
        text=text,
        controls=tuple(controls),
    )


def transfer_screen() -> Screen:
    """
    Build a form: two account pickers, an amount, and a submit button.
    """
    form = "content>group:0>group:2>form:0"
    controls = _nav("content>group:0>group:1") + [
        _control(
            "amount",
            "text_field",
            "Amount",
            f"{form}>text_field:0",
            (0.45, 0.40, 0.10, 0.02),
            label="Amount:",
        ),
        _control(
            "from",
            "combo_box",
            "From account",
            f"{form}>combo_box:0",
            (0.45, 0.44, 0.10, 0.02),
            label="From account #",
        ),
        _control(
            "to",
            "combo_box",
            "To account",
            f"{form}>combo_box:1",
            (0.45, 0.48, 0.10, 0.02),
            label="to account #",
        ),
        _control(
            "submit",
            "button",
            "Transfer",
            f"{form}>button:0",
            (0.45, 0.53, 0.06, 0.03),
        ),
    ]
    return Screen(
        app="Browser",
        window_title="Bank | Transfer Funds",
        text="Transfer Funds Amount: $ From account # to account #",
        controls=tuple(controls),
    )


def login_screen() -> Screen:
    """
    Build a sign-in form with labelled fields.
    """
    form = "content>group:0>group:1>form:0"
    controls = [
        _control(
            "user",
            "text_field",
            "",
            f"{form}>text_field:0",
            (0.20, 0.40, 0.08, 0.02),
            label="Username",
        ),
        _control(
            "pass",
            "text_field",
            "",
            f"{form}>text_field:1",
            (0.20, 0.44, 0.08, 0.02),
            label="Password",
        ),
        _control(
            "login",
            "button",
            "Log In",
            f"{form}>button:0",
            (0.20, 0.48, 0.05, 0.02),
        ),
        _control(
            "register",
            "link",
            "Register",
            "content>group:0>group:1>link:0",
            (0.20, 0.52, 0.05, 0.02),
        ),
    ]
    return Screen(
        app="Browser",
        window_title="Bank | Welcome",
        text="Customer Login Username Password",
        controls=tuple(controls),
    )


SCREENS: Dict[str, Callable[[], Screen]] = {
    "accounts": accounts_screen,
    "transfer": transfer_screen,
    "login": login_screen,
}


# #############################################################################
# Operators
# #############################################################################


def _with(screen: Screen, controls: Sequence[digest.Control]) -> Screen:
    return dataclasses.replace(screen, controls=tuple(controls))


def _moved(control: digest.Control, **box: float) -> digest.Control:
    return dataclasses.replace(
        control, box=dataclasses.replace(control.box, **box)
    )


def recased(screen: Screen, rng: random.Random) -> Screen:
    """
    Change case and spacing of every name ("Log In" -> "LOG  IN").
    """
    del rng
    return _with(
        screen,
        [
            dataclasses.replace(c, name=c.name.upper().replace(" ", "  "))
            for c in screen.controls
        ],
    )


def renamed(screen: Screen, rng: random.Random) -> Screen:
    """
    Reword one interactive control ("Transfer" -> "Transfer now").
    """
    named = [c for c in screen.controls if c.role in _INTERACTIVE and c.name]
    victim = rng.choice(named)
    return _with(
        screen,
        [
            dataclasses.replace(c, name=f"{c.name} now") if c is victim else c
            for c in screen.controls
        ],
    )


def reordered_rows(screen: Screen, rng: random.Random) -> Screen:
    """
    Shuffle table rows: their paths and positions change, names do not.
    """
    rows = [c for c in screen.controls if "table_row:" in c.path]
    if len(rows) < 2:
        return screen
    order = list(range(len(rows)))
    while order == sorted(order):
        rng.shuffle(order)
    slots = [(r.path, r.box) for r in rows]
    moved = {
        row.ref: dataclasses.replace(
            row, path=slots[order[i]][0], box=slots[order[i]][1]
        )
        for i, row in enumerate(rows)
    }
    return _with(screen, [moved.get(c.ref, c) for c in screen.controls])


def banner(screen: Screen, rng: random.Random) -> Screen:
    """
    Insert a dismissable banner at the top: sibling indices and y shift.
    """
    del rng

    def shift(path: str) -> str:
        return re.sub(
            r"^content>group:0>group:(\d+)",
            lambda m: f"content>group:0>group:{int(m.group(1)) + 1}",
            path,
        )

    shifted = [
        dataclasses.replace(
            c,
            path=shift(c.path),
            box=dataclasses.replace(c.box, y=c.box.y + 0.06),
        )
        for c in screen.controls
    ]
    note = _control(
        "banner",
        "button",
        "Dismiss",
        "content>group:0>group:0>button:0",
        (0.80, 0.22, 0.05, 0.02),
    )
    return _with(screen, [note, *shifted])


def moved_button(screen: Screen, rng: random.Random) -> Screen:
    """
    Move one button or link to another container and across the page.
    """
    movable = [c for c in screen.controls if c.role in ("button", "link")]
    victim = rng.choice(movable)
    return _with(
        screen,
        [
            (
                dataclasses.replace(
                    _moved(c, x=min(c.box.x + 0.35, 0.9)),
                    path=f"content>group:0>group:9>{c.role}:0",
                )
                if c is victim
                else c
            )
            for c in screen.controls
        ],
    )


def resized(screen: Screen, rng: random.Random) -> Screen:
    """
    Narrow the window: content reflows, so x and widths shrink.
    """
    del rng
    return _with(
        screen,
        [
            _moved(c, x=0.1 + (c.box.x - 0.1) * 0.7, w=c.box.w * 0.7)
            for c in screen.controls
        ],
    )


def translated(screen: Screen, rng: random.Random) -> Screen:
    """
    Translate names and labels, as a change of UI language does.
    """
    del rng

    def tr(text: str) -> str:
        return _WORDS.get(text.lower().rstrip(":# ").strip(), text)

    return _with(
        screen,
        [
            dataclasses.replace(c, name=tr(c.name), label=tr(c.label))
            for c in screen.controls
        ],
    )


def _both(first: Operator, second: Operator) -> Operator:
    """
    Apply two changes, as a redesign does.
    """

    def apply(screen: Screen, rng: random.Random) -> Screen:
        return second(first(screen, rng), rng)

    return apply


OPERATORS: Dict[str, Operator] = {
    "recased": recased,
    "renamed": renamed,
    "reordered_rows": reordered_rows,
    "banner": banner,
    "moved_button": moved_button,
    "resized": resized,
    "translated": translated,
    "translated+banner": _both(translated, banner),
    "renamed+banner": _both(renamed, banner),
    "translated+reordered_rows": _both(translated, reordered_rows),
    "translated+resized": _both(translated, resized),
}


# #############################################################################
# Score
# #############################################################################


@dataclasses.dataclass
class Score:
    """
    What one operator did to replay, over every screen and target.

    :ivar targets: Recorded steps resolved.
    :ivar correct: Resolved to the same control.
    :ivar wrong: Resolved to a different control.
    :ivar escalated: Resolved to nothing or to several controls.
    :ivar coverages: Per changed screen, the coverage of every original
        screen's fingerprint on it, and which original it really is.
    :ivar located: Per changed screen, whether ``localize.locate`` (with
        the title checks a recorded node carries) named the right
        screen.
    """

    targets: int = 0
    correct: int = 0
    wrong: int = 0
    escalated: int = 0
    coverages: List[Tuple[str, Dict[str, float]]] = dataclasses.field(
        default_factory=list
    )
    located: List[bool] = dataclasses.field(default_factory=list)


def evaluate(seeds: Sequence[int] = tuple(range(5))) -> Dict[str, Score]:
    """
    Apply every operator to every screen and score replay's decisions.

    :param seeds: Random seeds; each picks different victims for the
        operators that change one control.
    :return: A score per operator.
    """
    scores: Dict[str, Score] = {}
    for name, operator in OPERATORS.items():
        score = scores.setdefault(name, Score())
        for seed in seeds:
            rng = random.Random(seed)
            originals = {key: build() for key, build in SCREENS.items()}
            changed = {key: operator(s, rng) for key, s in originals.items()}
            known = _graph(originals)
            for key, original in originals.items():
                _score_targets(score, original, changed[key])
                live = set(odfinger.of(changed[key]))
                score.coverages.append(
                    (
                        key,
                        {
                            other: odfinger.coverage(odfinger.of(screen), live)
                            for other, screen in originals.items()
                        },
                    )
                )
                score.located.append(localize.locate(changed[key], known) == key)
    return scores


def _graph(originals: Dict[str, Screen]) -> graph.AppGraph:
    """
    Record each original screen as a node, as discovery would.
    """
    return graph.AppGraph(
        vendor_id="bank",
        nodes=[
            graph.Node(
                id=key,
                description=screen.window_title,
                checks=[
                    graph.TitleMatches(pattern=re.escape(screen.window_title))
                ],
                fingerprint=odfinger.of(screen),
            )
            for key, screen in originals.items()
        ],
        edges=[],
    )


def pick(coverages: Dict[str, float], threshold: float) -> str:
    """
    Name the screen coverage alone would pick, as localize ranks it.

    :return: The screen id, ``"tie"`` when the best is shared, or
        ``"none"`` when nothing reaches ``threshold`` (localize then
        falls back to the title checks).
    """
    above = {k: c for k, c in coverages.items() if c >= threshold}
    if not above:
        return "none"
    best = max(above.values())
    winners = [k for k, c in above.items() if c == best]
    return winners[0] if len(winners) == 1 else "tie"


def _score_targets(score: Score, original: Screen, changed: Screen) -> None:
    for control in original.controls:
        if control.role not in _INTERACTIVE:
            continue
        stack = recdng.strategies_for(control).strategies
        result = locate.resolve_target(stack, changed)
        score.targets += 1
        if isinstance(result, locate.ResolutionFailure):
            score.escalated += 1
        elif result.control.ref == control.ref:
            score.correct += 1
        else:
            score.wrong += 1


def report(scores: Dict[str, Score]) -> str:
    """
    Render the per-operator table and the recognition threshold sweep.
    """
    lines = [
        "| UI change | Steps | Same control | Wrong control | Escalated "
        "| Screen located |",
        "|---|---|---|---|---|---|",
    ]
    for name, s in scores.items():
        lines.append(
            f"| {name} | {s.targets} | {100 * s.correct / s.targets:.0f}% | "
            f"{s.wrong} | {100 * s.escalated / s.targets:.0f}% | "
            f"{100 * sum(s.located) / len(s.located):.0f}% |"
        )
    lines += [
        "",
        "| Threshold | Right screen | Wrong screen | Tie | Below threshold |",
        "|---|---|---|---|---|",
    ]
    cases = [c for s in scores.values() for c in s.coverages]
    for threshold in THRESHOLDS:
        picks = [(truth, pick(cov, threshold)) for truth, cov in cases]
        right = sum(1 for truth, got in picks if got == truth)
        tie = sum(1 for _, got in picks if got == "tie")
        none = sum(1 for _, got in picks if got == "none")
        wrong = len(picks) - right - tie - none
        lines.append(
            f"| {threshold:.1f} | {100 * right / len(picks):.0f}% | "
            f"{100 * wrong / len(picks):.0f}% | {100 * tie / len(picks):.0f}% | "
            f"{100 * none / len(picks):.0f}% |"
        )
    located = [ok for s in scores.values() for ok in s.located]
    lines.append(
        f"\nWith the title checks, localize named the right screen in "
        f"{100 * sum(located) / len(located):.0f}% of changed screens."
    )
    return "\n".join(lines)
