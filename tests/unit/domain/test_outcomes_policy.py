from __future__ import annotations

import json
import pathlib

import pytest

import operant.domain.approval as approval
import operant.domain.models.actions as actions
import operant.domain.models.artifact as artifact
import operant.domain.models.graph as graph
import operant.domain.models.plan as mdplan
import operant.domain.outcomes as outcomes
import operant.domain.policy as policy
import operant.domain.redaction as redact
import tests.support.screens as screens


def test_title_and_text_conditions() -> None:
    d = screens.digest()
    assert outcomes.evaluate_condition(
        graph.TitleMatches(pattern=r"Accounts Overview"), d
    )
    assert not outcomes.evaluate_condition(
        graph.TitleMatches(pattern=r"Account Details"), d
    )
    d = screens.digest(text="Accounts Overview", dialog="Session about to expire")
    assert outcomes.evaluate_condition(
        graph.TextMatches(pattern="session about to expire"), d
    )


OUTCOME_EDGES = [
    graph.OutcomeEdge(
        id="notfound",
        at="overview",
        when=graph.TextMatches(pattern="could not be found"),
        handle=graph.BusinessOutcomeHandle(outcome="RECORD_NOT_FOUND"),
    ),
    graph.OutcomeEdge(
        id="app-error",
        at="*",
        when=graph.TextMatches(pattern="internal error"),
        handle=graph.FailHandle(failure_class="app_error"),
    ),
]


def test_node_scoped_outcome_edges_rank_before_global() -> None:
    d = screens.digest(
        text="An internal error has occurred. The record could not be found."
    )
    matched = outcomes.match_outcome_edges(OUTCOME_EDGES, "overview", d)
    assert matched is not None and matched.id == "notfound"
    # At a different node, only the global edge applies.
    matched = outcomes.match_outcome_edges(OUTCOME_EDGES, "login", d)
    assert matched is not None and matched.id == "app-error"


def test_extraction_and_missing() -> None:
    spec = artifact.ExtractSpec(
        output="balance", pattern=r"Balance: (-?\$[\d,.]+)"
    )
    d = screens.digest(text="Account Details Balance: $515.50 Available: $515.50")
    outputs, missing = outcomes.run_extraction([spec], d)
    assert outputs == {"balance": "$515.50"}
    assert missing == []
    outputs, missing = outcomes.run_extraction(
        [spec], screens.digest(text="Error!")
    )
    assert outputs == {}
    assert missing == ["balance"]


# Column by column, as an accessibility tree often reads a table.
_COLUMNS = "Account 12345 12456 13344 Balance* -$2300.00 $10.45 $1231.10"
# Row by row.
_ROWS = "Account Balance* 12345 -$2300.00 12456 $10.45 13344 $1231.10"


@pytest.mark.parametrize(
    "pattern, text, unread",
    [
        # Reads the first record only: no sibling can take its place.
        (r"Account\s+12345.*?Balance\*\s+([-$\d,.]+)", _COLUMNS, "12456"),
        # Anchored on the record's own row: every sibling reads its row.
        (r"12345\s+([-$\d,.]+)", _ROWS, None),
        # Matches the same text whatever the input: reads one record.
        (r"Account Balance\*.*?([-$\d,.]+)(?:.*12345)?", _ROWS, "12456"),
        # Only one record visible: nothing to compare against.
        (r"12345\s+([-$\d,.]+)", "Account 12345 Balance -$2300.00", None),
    ],
)
def test_an_input_anchored_pattern_must_read_sibling_records(
    pattern: str, text: str, unread: object
) -> None:
    assert outcomes.unread_sibling(pattern, text, "12345") == unread


POLICY = policy.Policy(
    id="test",
    allowed_apps=["Google Chrome"],
    allowed_url_patterns=[r"^http://localhost:808[01]/"],
    allowed_action_kinds=["launch", "click", "fill", "select", "press"],
    mutating_control_patterns=["open new account", "transfer", "send"],
)


def _with_approval(
    approval_policy: approval.ApprovalPolicy,
) -> policy.Policy:
    return POLICY.model_copy(update={"approval": approval_policy})


def test_policy_denies_disallowed_kind() -> None:
    d = policy.evaluate_action(POLICY, actions.SurfaceAction(kind="scroll"))
    assert d.verdict == "deny" and "not in the allowlist" in d.reason


def test_blocked_launch_asks_for_scope_with_the_grants_that_lift_it() -> None:
    d = policy.evaluate_action(
        POLICY, actions.SurfaceAction(kind="launch", app="Terminal")
    )
    assert d.verdict == "needs_approval" and d.approval is not None
    assert d.approval.kind == "scope"
    assert [(g.kind, g.pattern) for g in d.approval.proposed_grants] == [
        ("app", "Terminal")
    ]
    web = actions.SurfaceAction(
        kind="launch", app="Google Chrome", url="https://evil.example.com/x"
    )
    d = policy.evaluate_action(POLICY, web)
    assert d.verdict == "needs_approval" and "outside allowed" in d.reason
    assert d.approval is not None
    assert [g.kind for g in d.approval.proposed_grants] == ["url"]
    assert "example\\.com" in d.approval.proposed_grants[0].pattern
    both = actions.SurfaceAction(
        kind="launch", app="Safari", url="https://web.whatsapp.com/"
    )
    d = policy.evaluate_action(POLICY, both)
    assert d.approval is not None
    assert [g.kind for g in d.approval.proposed_grants] == ["app", "url"]


def test_launch_with_no_coarse_grant_is_denied() -> None:
    d = policy.evaluate_action(
        POLICY,
        actions.SurfaceAction(kind="launch", app=None, url="https:///nohost"),
    )
    assert d.verdict == "deny"


def test_local_hosts_are_granted_verbatim() -> None:
    assert policy.registrable_domain("http://localhost:8080/") == "localhost"
    assert policy.registrable_domain("http://127.0.0.1/") == "127.0.0.1"
    assert policy.registrable_domain("https://a.b.example.com/") == (
        "example.com"
    )
    custom = frozenset({"devbox"})
    assert policy.registrable_domain("http://devbox/", local_hosts=custom) == (
        "devbox"
    )
    assert policy.registrable_domain("http://devbox.corp.lan/") == "corp.lan"
    assert policy.registrable_domain("mailto:") is None


def test_a_grant_never_widens_to_a_public_suffix() -> None:
    assert policy.registrable_domain("https://online.bank.co.uk/") == (
        "bank.co.uk"
    )
    assert policy.registrable_domain("https://me.github.io/app") == (
        "me.github.io"
    )


def test_mutating_click_needs_approval_unless_policy_opts_out() -> None:
    action = actions.SurfaceAction(
        kind="click", ref="c1", target_text='button "Open New Account"'
    )
    d = policy.evaluate_action(POLICY, action)
    assert d.verdict == "needs_approval" and d.risk == "mutating"
    assert d.approval is not None
    assert d.approval.kind == "mutating"
    assert "Open New Account" in d.approval.summary
    relaxed = _with_approval(approval.ApprovalPolicy(mutating=False))
    d = policy.evaluate_action(relaxed, action)
    assert d.allowed and d.risk == "mutating"
    safe_click = actions.SurfaceAction(
        kind="click", ref="c1", target_text="Accounts Overview"
    )
    assert policy.classify_risk(POLICY, safe_click) == "safe"


def test_enter_is_mutating_only_with_a_live_mutating_control_on_screen() -> None:
    enter = actions.SurfaceAction(kind="press", key="Enter")
    send_button = screens.digest(
        controls=(screens.control("c1", "button", name="Send"),)
    )
    assert policy.classify_risk(POLICY, enter, send_button) == "mutating"
    d = policy.evaluate_action(POLICY, enter, digest=send_button)
    assert d.verdict == "needs_approval" and d.approval is not None
    assert d.approval.kind == "mutating"
    assert "Send" in d.approval.summary
    text_field = screens.digest(
        controls=(screens.control("c1", "text_field", label="Send a message"),)
    )
    assert policy.classify_risk(POLICY, enter, text_field) == "safe"
    disabled = screens.digest(
        controls=(screens.control("c1", "button", name="Send", enabled=False),)
    )
    assert policy.classify_risk(POLICY, enter, disabled) == "safe"
    assert policy.classify_risk(POLICY, enter, None) == "safe"
    tab = actions.SurfaceAction(kind="press", key="Tab")
    assert policy.classify_risk(POLICY, tab, send_button) == "safe"


def test_sensitive_fill_is_detected_from_the_control_and_never_echoes() -> None:
    password = screens.control("c1", "text_field", label="Password", value="••••")
    d = policy.evaluate_action(
        POLICY,
        actions.SurfaceAction(
            kind="fill", ref="c1", value="hunter2-pw", target_text="Password"
        ),
        control=password,
        app="Google Chrome",
    )
    assert d.verdict == "needs_approval" and d.approval is not None
    assert d.approval.kind == "sensitive_fill"
    assert d.approval.details["data_class"] == "credential"
    assert "hunter2" not in d.reason and "hunter2" not in d.approval.summary
    assert "hunter2" not in " ".join(d.approval.details.values())


def test_sensitive_fill_is_detected_from_the_value_alone() -> None:
    field = screens.control("c1", "text_field", label="Card")
    d = policy.evaluate_action(
        POLICY,
        actions.SurfaceAction(kind="fill", ref="c1", value="4111 1111 1111 1111"),
        control=field,
    )
    assert d.approval is not None
    assert d.approval.details["data_class"] == "financial"
    plain = policy.evaluate_action(
        POLICY,
        actions.SurfaceAction(kind="fill", ref="c1", value="hello"),
        control=field,
    )
    assert plain.allowed


def test_caller_tag_counts_and_export_outranks_fill() -> None:
    field = screens.control("c1", "text_area", name="Message")
    tagged = actions.SurfaceAction(
        kind="fill", ref="c1", value="$10.45", data_class="financial"
    )
    d = policy.evaluate_action(POLICY, tagged, control=field, app="WhatsApp")
    assert d.approval is not None and d.approval.kind == "sensitive_fill"
    exported = actions.SurfaceAction(
        kind="fill",
        ref="c1",
        value="$10.45",
        data_class="financial",
        export_from="parabank",
    )
    d = policy.evaluate_action(POLICY, exported, control=field, app="WhatsApp")
    assert d.approval is not None and d.approval.kind == "sensitive_export"
    assert d.approval.details["from_app"] == "parabank"
    assert d.approval.details["to_app"] == "WhatsApp"
    harmless = actions.SurfaceAction(
        kind="fill", ref="c1", value="hi", export_from="parabank"
    )
    assert policy.evaluate_action(POLICY, harmless, control=field).allowed


def test_sensitive_policy_opt_outs() -> None:
    field = screens.control("c1", "text_field", label="Password")
    action = actions.SurfaceAction(kind="fill", ref="c1", value="pw-value")
    no_fill = _with_approval(approval.ApprovalPolicy(sensitive_fill="off"))
    assert policy.evaluate_action(no_fill, action, control=field).allowed
    vendor = _with_approval(
        approval.ApprovalPolicy(sensitive_field_patterns=["financial:amount"])
    )
    amount = screens.control("c2", "text_field", label="Amount")
    d = policy.evaluate_action(
        vendor,
        actions.SurfaceAction(kind="fill", ref="c2", value="100"),
        control=amount,
    )
    assert d.approval is not None
    assert d.approval.details["data_class"] == "financial"


def test_select_is_classified_like_fill() -> None:
    combo = screens.control("c1", "combo_box", label="From account")
    vendor = _with_approval(
        approval.ApprovalPolicy(
            sensitive_field_patterns=["financial:from account"]
        )
    )
    d = policy.evaluate_action(
        vendor,
        actions.SurfaceAction(kind="select", ref="c1", option="13344"),
        control=combo,
    )
    assert d.approval is not None and d.approval.kind == "sensitive_fill"


def test_fingerprint_ignores_the_value_but_not_the_question() -> None:
    a = actions.SurfaceAction(
        kind="fill",
        ref="c1",
        value="one",
        target_text="Password",
        data_class="credential",
    )
    b = actions.SurfaceAction(
        kind="fill",
        ref="c1",
        value="two",
        target_text="Password",
        data_class="credential",
    )
    fp = approval.fingerprint
    assert fp("sensitive_fill", a) == fp("sensitive_fill", b)
    assert fp("sensitive_fill", a) != fp("sensitive_fill", a, app="Chrome")
    stepped = actions.SurfaceAction(
        kind="fill",
        ref="c1",
        value="one",
        target_text="Password",
        data_class="credential",
        step="edge-2",
    )
    assert fp("sensitive_fill", a) != fp("sensitive_fill", stepped)
    other_field = actions.SurfaceAction(
        kind="fill",
        ref="c1",
        value="one",
        target_text="Username",
        data_class="credential",
    )
    assert fp("sensitive_fill", a) != fp("sensitive_fill", other_field)
    other_class = actions.SurfaceAction(
        kind="fill",
        ref="c1",
        value="one",
        target_text="Password",
        data_class="pii",
    )
    assert fp("sensitive_fill", a) != fp("sensitive_fill", other_class)


def test_redactor_masks_secrets_deep() -> None:
    r = redact.Redactor()
    r.add_secret("hunter2-password")
    out = r.redact_deep({"note": "typed hunter2-password into the form"})
    assert out == {"note": "typed [REDACTED] into the form"}


def test_redactor_from_env_reads_the_given_mapping_only() -> None:
    env = {"PARABANK_PASSWORD": "pw-value", "HOME": "/Users/x"}
    r = redact.redactor_from_env(env)
    assert r.redact("pw-value at /Users/x") == "[REDACTED] at /Users/x"


def test_secret_reference_fills_run_unattended_unless_policy_says_always() -> (
    None
):
    field = screens.control("c1", "text_field", label="Password")
    held = actions.SurfaceAction(
        kind="fill",
        ref="c1",
        value="pw-value",
        data_class="credential",
        secret_ref="password",
    )
    d = policy.evaluate_action(POLICY, held, control=field, app="Google Chrome")
    assert d.allowed and '"password"' in d.reason
    assert "pw-value" not in d.reason
    literal = actions.SurfaceAction(
        kind="fill", ref="c1", value="pw-value", data_class="credential"
    )
    d = policy.evaluate_action(POLICY, literal, control=field)
    assert d.approval is not None and d.approval.kind == "sensitive_fill"
    strict = _with_approval(approval.ApprovalPolicy(sensitive_fill="always"))
    d = policy.evaluate_action(strict, held, control=field)
    assert d.approval is not None and d.approval.kind == "sensitive_fill"


def _click_risk(target_text: str) -> str:
    click = actions.SurfaceAction(kind="click", target_text=target_text)
    return policy.classify_risk(POLICY, click, None)


def test_a_neighbours_label_does_not_make_navigation_mutating() -> None:
    assert _click_risk("Accounts Overview | Open New Account") == "safe"


def test_a_generic_button_is_judged_by_its_label() -> None:
    assert _click_risk("Go | Transfer Funds") == "mutating"
    assert _click_risk(" | Transfer Funds") == "mutating"


def test_a_mutating_name_is_mutating_whatever_its_label() -> None:
    assert _click_risk("Transfer Funds | Accounts") == "mutating"


_BASE_FILE = (
    pathlib.Path(__file__).parents[3] / "policies" / "discovery-base.json"
)
BASE = policy.Policy.model_validate(json.loads(_BASE_FILE.read_text())["policy"])


@pytest.mark.parametrize(
    "target_text, expected",
    [
        # Whole words: a mutating word inside another word is not a match.
        ("Postal code", "safe"),
        ("Design", "safe"),
        ("Address", "safe"),
        # Safe phrases blank out the mutating word they contain.
        ("Sign in", "safe"),
        ("Sort order", "safe"),
        ("Apply filters", "safe"),
        ("Cancel", "safe"),
        # Verbs that change data and used to pass as safe.
        ("Save", "mutating"),
        ("Create invoice", "mutating"),
        ("Add to cart", "mutating"),
        ("Update address", "mutating"),
        ("Cancel subscription", "mutating"),
        # A safe phrase does not hide a mutating one next to it.
        ("View and pay bill", "mutating"),
        ("Sign up", "mutating"),
    ],
)
def test_the_base_policy_judges_controls_by_whole_words(
    target_text: str, expected: str
) -> None:
    click = actions.SurfaceAction(kind="click", target_text=target_text)
    assert policy.classify_risk(BASE, click) == expected


def test_a_shortcut_chord_is_mutating() -> None:
    chord = actions.SurfaceAction(kind="press", key="cmd+s")
    assert policy.classify_risk(POLICY, chord, screens.digest()) == "mutating"


def test_delete_is_mutating_only_outside_a_text_field() -> None:
    delete = actions.SurfaceAction(kind="press", key="Delete")
    item_list = screens.digest(
        controls=(screens.control("c1", "row", name="Report.pdf"),)
    )
    assert policy.classify_risk(POLICY, delete, item_list) == "mutating"
    editing = screens.digest(
        controls=(screens.control("c1", "text_field", label="Message"),)
    )
    assert policy.classify_risk(POLICY, delete, editing) == "safe"


def test_strict_mode_gates_unlisted_buttons_only() -> None:
    strict = POLICY.model_copy(
        update={"strict": True, "safe_control_patterns": ["search"]}
    )
    button = screens.control("c1", "button", name="Archive")
    click = actions.SurfaceAction(kind="click", ref="c1", target_text="Archive")
    assert policy.classify_risk(strict, click, None, button) == "mutating"
    assert policy.classify_risk(POLICY, click, None, button) == "safe"
    link = screens.control("c1", "link", name="Archive")
    assert policy.classify_risk(strict, click, None, link) == "safe"
    search = actions.SurfaceAction(kind="click", ref="c1", target_text="Search")
    assert policy.classify_risk(strict, search, None, button) == "safe"
    d = policy.evaluate_action(strict, click, control=button)
    assert d.verdict == "needs_approval"


def test_typed_checks_read_text_controls_and_outputs() -> None:
    screen = screens.digest(
        [screens.control(role="link", name="Log Out")],
        text="Transfer Complete! Confirmation 7731",
    )
    checks = [
        mdplan.ScreenCheck(kind="text_present", value="transfer complete"),
        mdplan.ScreenCheck(kind="control_present", value="log out"),
        mdplan.ScreenCheck(kind="output_matches", output="ref", value=r"^\d+$"),
    ]
    assert outcomes.failed_checks(checks, screen, {"ref": "7731"}) == []
    assert outcomes.failed_checks(checks, screen, {"ref": "n/a"}) == [
        r"output_matches ref '^\d+$'"
    ]
    assert len(outcomes.failed_checks(checks, None, {})) == 3
