"""Policy model and the pure enforcement decision.

Both discovery and replay act through the gateway's policy guard, so no
code path can reach the OS without a policy check. Decisions are
three-state: allow, deny, or needs_approval. The last carries the exact
question a human must answer (scope widening, a mutating control, a
sensitive value typed, a sensitive value exported to another app). The
value itself never appears in a decision; humans see its class and
length.

Typical usage example:

  decision = evaluate_action(policy, action, digest=digest, app="Chrome")
  if decision.verdict == "deny":
      raise errors.PolicyViolationError(decision)

Import as:

import operant.domain.policy as policy
"""

from __future__ import annotations

import collections.abc
import re
import urllib.parse
from typing import Dict, Final, FrozenSet, List, Optional, Tuple

import pydantic

import operant.domain.approval as daapprov
import operant.domain.models.actions as actions
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as mddigest
import operant.domain.sensitivity as sensv

DEFAULT_LOCAL_HOSTS: Final[FrozenSet[str]] = frozenset({"localhost", "127.0.0.1"})

_ENTER_KEYS: Final = frozenset({"enter", "return", "kp_enter"})
_SUBMIT_ROLES: Final = frozenset({"button", "link", "menu_item"})
_IP_HOST_RE: Final = re.compile(r"[\d.]+")


# #############################################################################
# Policy
# #############################################################################


class Policy(pydantic.BaseModel):
    """
    The static allowlists an application runs under.

    :ivar id: Policy document id.
    :ivar allowed_apps: OS application names that may be launched.
    :ivar allowed_url_patterns: Regexes a launched URL must match.
    :ivar allowed_action_kinds: Surface action kinds that may run.
    :ivar mutating_control_patterns: Regexes naming controls that mutate
        application state.
    :ivar approval: Which approval gates are on.
    """

    id: str
    allowed_apps: List[str]
    allowed_url_patterns: List[str]
    allowed_action_kinds: List[str]
    mutating_control_patterns: List[str]
    approval: daapprov.ApprovalPolicy = daapprov.ApprovalPolicy()


def registrable_domain(
    url: str, *, local_hosts: FrozenSet[str] = DEFAULT_LOCAL_HOSTS
) -> Optional[str]:
    """
    Extract the registrable domain of a URL.

    :param url: The URL to inspect.
    :param local_hosts: Host names returned verbatim instead of being
        reduced to a registrable domain; IP literals are always returned
        verbatim.
    :return: The last two labels of the host (``example.com``), the host
        itself for local hosts and IP literals, or ``None`` when the URL
        has no host.
    """
    host = urllib.parse.urlparse(url).hostname
    if not host:
        # No host in the URL: nothing to reduce.
        domain = None
    elif host in local_hosts or _IP_HOST_RE.fullmatch(host):
        # Local host or IP literal: return it verbatim.
        domain = host
    else:
        # Otherwise reduce the host to its last two labels.
        parts = host.split(".")
        domain = ".".join(parts[-2:]) if len(parts) >= 2 else host
    return domain


def propose_scope(
    action: actions.SurfaceAction,
    reason: str,
    *,
    local_hosts: FrozenSet[str] = DEFAULT_LOCAL_HOSTS,
) -> Optional[daapprov.ScopeRequest]:
    """
    Proposes the coarse grant a human would approve for a launch.

    The whole registrable domain for a URL, the whole scheme for a non-
    HTTP URL, the whole app for a native launch.

    :param action: The blocked action; only ``launch`` proposes
        anything.
    :param reason: Why the agent tried it.
    :param local_hosts: See ``registrable_domain``.
    :return: The request, or ``None`` when nothing coarse can be
        proposed.
    """
    request: Optional[daapprov.ScopeRequest] = None
    if action.kind == "launch":
        if action.url and action.url.startswith("http"):
            # Web URL: propose the whole registrable domain.
            domain = registrable_domain(action.url, local_hosts=local_hosts)
            if domain is not None:
                escaped = re.escape(domain)
                pattern = rf"^https?://([a-z0-9-]+\.)*{escaped}(:\d+)?(/|$)"
                request = daapprov.ScopeRequest(
                    kind="url",
                    value=action.url,
                    proposed=pattern,
                    reason=reason,
                )
        elif action.url:
            # Non-HTTP URL: propose the whole scheme.
            scheme = action.url.split(":", 1)[0]
            request = daapprov.ScopeRequest(
                kind="url",
                value=action.url,
                proposed=rf"^{re.escape(scheme)}:",
                reason=reason,
            )
        elif action.app:
            # Native launch: propose the whole app.
            request = daapprov.ScopeRequest(
                kind="app",
                value=action.app,
                proposed=action.app,
                reason=reason,
            )
    return request


def _mutating_match(policy: Policy, text: str) -> Optional[str]:
    """
    Return the first mutating-control pattern the text matches.
    """
    found = None
    for pattern in policy.mutating_control_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            found = pattern
            break
    return found


def _mutating_trigger(
    policy: Policy,
    action: actions.SurfaceAction,
    screen: Optional[mddigest.ScreenDigest],
) -> Optional[Tuple[str, str]]:
    """
    Find what makes the action mutating, if anything.

    Enter is a submit when a mutating-labelled control is live on
    screen; that is how a chat sends, and how a click-only check gets
    bypassed.

    :param policy: The governing policy.
    :param action: The action about to run.
    :param screen: The current digest, when one is available.
    :return:``(what the human would read, matched pattern)`` or
        ``None``.
    """
    if action.kind == "click":
        pattern = _mutating_match(policy, action.target_text)
        return (f'click "{action.target_text}"', pattern) if pattern else None
    is_enter = (action.key or "").lower() in _ENTER_KEYS
    if action.kind == "press" and is_enter and screen is not None:
        for control in screen.controls:
            if not control.enabled or control.role not in _SUBMIT_ROLES:
                continue
            text = " | ".join(x for x in (control.name, control.label) if x)
            pattern = _mutating_match(policy, text)
            if pattern:
                what = (
                    f'press {action.key} with {control.role} "{text}" on screen'
                )
                return (what, pattern)
    return None


def classify_risk(
    policy: Policy,
    action: actions.SurfaceAction,
    digest: Optional[mddigest.ScreenDigest] = None,
) -> daapprov.Risk:
    """
    Classify an action as ``safe`` or ``mutating``.

    :param policy: The governing policy.
    :param action: The action about to run.
    :param digest: The current digest, when one is available.
    :return:``mutating`` when a mutating trigger is found, else
        ``safe``.
    """
    risk: daapprov.Risk = (
        "mutating" if _mutating_trigger(policy, action, digest) else "safe"
    )
    return risk


def _app_blocked(
    policy: Policy,
    action: actions.SurfaceAction,
    grants: collections.abc.Sequence[daapprov.ScopeGrant],
) -> bool:
    """
    Whether the action's app is outside the allowlist and the grants.
    """
    if action.app is None or action.app in policy.allowed_apps:
        blocked = False
    else:
        blocked = not any(
            g.kind == "app" and g.pattern == action.app for g in grants
        )
    return blocked


def _url_blocked(
    policy: Policy,
    action: actions.SurfaceAction,
    grants: collections.abc.Sequence[daapprov.ScopeGrant],
) -> bool:
    """
    Whether the action's URL is outside the allowlist and the grants.
    """
    url = action.url
    if url is None:
        blocked = False
    elif any(re.search(p, url) for p in policy.allowed_url_patterns):
        blocked = False
    else:
        blocked = not any(
            g.kind == "url" and re.search(g.pattern, url) for g in grants
        )
    return blocked


def _scope_grants_for(
    policy: Policy,
    action: actions.SurfaceAction,
    grants: collections.abc.Sequence[daapprov.ScopeGrant],
    *,
    local_hosts: FrozenSet[str],
) -> Tuple[Optional[str], Optional[Tuple[daapprov.ScopeGrant, ...]]]:
    """
    Find why a launch is blocked and the grants that would lift it.

    A web launch through a browser needs both the browser app and the
    domain; the generated profile allows exactly that pair.

    :return:``(block reason, grants)``: reason ``None`` when not
        blocked; grants ``None`` when no coarse grant can lift the
        block.
    """
    needed: List[daapprov.ScopeGrant] = []
    reasons: List[str] = []
    url_unliftable = False
    if _app_blocked(policy, action, grants) and action.app is not None:
        reasons.append(f'app "{action.app}" is not in the allowlist')
        needed.append(daapprov.ScopeGrant(kind="app", pattern=action.app))
    if _url_blocked(policy, action, grants) and action.url is not None:
        reasons.append(f'url "{action.url}" is outside allowed patterns')
        request = propose_scope(
            actions.SurfaceAction(kind="launch", url=action.url),
            "",
            local_hosts=local_hosts,
        )
        if request is None:
            url_unliftable = True
        else:
            needed.append(
                daapprov.ScopeGrant(kind="url", pattern=request.proposed)
            )
    result: Tuple[Optional[str], Optional[Tuple[daapprov.ScopeGrant, ...]]]
    if url_unliftable:
        # A blocked URL that no coarse grant can cover: deny outright.
        result = ("; ".join(reasons), None)
    elif not reasons:
        # Nothing was blocked: the launch is within scope.
        result = (None, ())
    else:
        # Blocked but liftable: return the grants that would clear it.
        result = ("; ".join(reasons), tuple(needed))
    return result


def _evaluate_launch(
    policy: Policy,
    action: actions.SurfaceAction,
    grants: collections.abc.Sequence[daapprov.ScopeGrant],
    *,
    app: str,
    local_hosts: FrozenSet[str],
) -> Optional[daapprov.PolicyDecision]:
    """
    Decides a launch against the scope allowlists and grants.
    """
    blocked, needed = _scope_grants_for(
        policy, action, grants, local_hosts=local_hosts
    )
    if blocked is None:
        # Scope is clear: no launch decision to make here.
        decision = None
    elif not needed:
        # Blocked with no way to widen: deny.
        decision = daapprov.PolicyDecision("deny", "safe", blocked)
    else:
        # Blocked but a human could widen the scope: ask.
        target = action.url or action.app or ""
        grant_text = ", ".join(f"{g.kind} {g.pattern!r}" for g in needed)
        decision = daapprov.PolicyDecision(
            "needs_approval",
            "safe",
            f"{blocked}; a human may widen the scope",
            approval=daapprov.ApprovalRequest(
                kind="scope",
                summary=f"open {target!r}",
                details={
                    "app": action.app or "",
                    "url": action.url or "",
                    "grants": grant_text,
                },
                fingerprint=daapprov.fingerprint("scope", action, app=app),
                action_kind=action.kind,
                app=app,
                step=action.step,
                proposed_grants=needed,
            ),
        )
    return decision


def _classify_typed(
    policy: Policy,
    action: actions.SurfaceAction,
    control: Optional[mddigest.Control],
) -> Tuple[Optional[str], str, artifact.DataClass]:
    """
    Return ``(typed value, field name, data class)`` for fill/select.
    """
    typed = action.value if action.kind == "fill" else action.option
    name = control.name if control is not None else action.target_text
    dc = sensv.strongest(
        action.data_class,
        sensv.classify(
            name=name,
            label=control.label if control is not None else None,
            value=typed,
            control_role=control.role if control is not None else None,
            control_value=control.value if control is not None else None,
            extra_patterns=policy.approval.sensitive_field_patterns,
        ),
    )
    return typed, name, dc


def _evaluate_export(
    action: actions.SurfaceAction,
    *,
    where: str,
    shown: str,
    details: Dict[str, str],
    app: str,
) -> daapprov.PolicyDecision:
    """
    Build the sensitive-export decision.
    """
    export_from = action.export_from or ""
    details.update({"from_app": export_from, "to_app": app})
    suffix = f" in {app}" if app else ""
    decision = daapprov.PolicyDecision(
        "needs_approval",
        "safe",
        f"sensitive value {shown} from {export_from} typed into "
        f'"{where}" in another app',
        approval=daapprov.ApprovalRequest(
            kind="sensitive_export",
            summary=f'send {shown} from {export_from} to "{where}"{suffix}',
            details=details,
            fingerprint=daapprov.fingerprint("sensitive_export", action, app=app),
            action_kind=action.kind,
            app=app,
            step=action.step,
        ),
    )
    return decision


def _evaluate_fill(
    policy: Policy,
    action: actions.SurfaceAction,
    control: Optional[mddigest.Control],
    *,
    app: str,
) -> Optional[daapprov.PolicyDecision]:
    """
    Decides a fill or select against the sensitivity gates.
    """
    typed, name, dc = _classify_typed(policy, action, control)
    decision: Optional[daapprov.PolicyDecision] = None
    if sensv.is_sensitive(dc):
        where = action.target_text or name or action.ref or "?"
        shown = sensv.preview(typed, dc)
        details = {"field": where, "data_class": dc, "value": shown}
        mode = policy.approval.sensitive_fill
        if action.export_from and policy.approval.sensitive_export:
            # Sensitive value crossing app boundaries: gate as an export.
            decision = _evaluate_export(
                action, where=where, shown=shown, details=details, app=app
            )
        elif action.secret_ref and mode != "always":
            # System-held secret reference: fill it unattended.
            decision = daapprov.PolicyDecision(
                "allow",
                "safe",
                f'secret reference "{action.secret_ref}" filled into '
                f'"{where}" (system-held, never model-visible)',
            )
        elif mode != "off":
            # A model- or caller-supplied literal: ask before typing it.
            decision = daapprov.PolicyDecision(
                "needs_approval",
                "safe",
                f'sensitive value {shown} typed into "{where}"',
                approval=daapprov.ApprovalRequest(
                    kind="sensitive_fill",
                    summary=f'{action.kind} "{where}" with {shown}',
                    details=details,
                    fingerprint=daapprov.fingerprint(
                        "sensitive_fill", action, app=app
                    ),
                    action_kind=action.kind,
                    app=app,
                    step=action.step,
                ),
            )
    return decision


def _evaluate_mutating(
    policy: Policy,
    action: actions.SurfaceAction,
    screen: Optional[mddigest.ScreenDigest],
    *,
    app: str,
) -> daapprov.PolicyDecision:
    """
    Decides the action against the mutating gate.
    """
    trigger = _mutating_trigger(policy, action, screen)
    if trigger is None:
        # No mutating trigger: the action is safe.
        decision = daapprov.PolicyDecision(
            "allow", "safe", "safe action within policy"
        )
    else:
        # A mutating control is in play.
        what, pattern = trigger
        if not policy.approval.mutating:
            # Policy permits mutation without asking.
            decision = daapprov.PolicyDecision(
                "allow",
                "mutating",
                f"mutating action allowed by policy: {what}",
            )
        else:
            # Policy requires a human to approve the mutation.
            decision = daapprov.PolicyDecision(
                "needs_approval",
                "mutating",
                f"mutating action requires human approval: {what}",
                approval=daapprov.ApprovalRequest(
                    kind="mutating",
                    summary=what,
                    details={"trigger": what, "pattern": pattern},
                    fingerprint=daapprov.fingerprint("mutating", action, app=app),
                    action_kind=action.kind,
                    app=app,
                    step=action.step,
                ),
            )
    return decision


def evaluate_action(
    policy: Policy,
    action: actions.SurfaceAction,
    *,
    grants: collections.abc.Sequence[daapprov.ScopeGrant] = (),
    digest: Optional[mddigest.ScreenDigest] = None,
    control: Optional[mddigest.Control] = None,
    app: str = "",
    local_hosts: FrozenSet[str] = DEFAULT_LOCAL_HOSTS,
) -> daapprov.PolicyDecision:
    """
    Evaluate one action against the policy.

    Gates run in order: action kind, scope (launch), sensitivity (fill
    and select), then the mutating trigger. The first gate that decides
    wins.

    :param policy: The governing policy.
    :param action: The action about to run.
    :param grants: Scope grants made earlier in the run.
    :param digest: The current screen digest, when one is available.
    :param control: The control the action targets, when resolved.
    :param app: Application the action targets.
    :param local_hosts: Host names treated as local by scope proposals.
    :return: The decision; ``needs_approval`` decisions carry the request.
    """
    if action.kind not in policy.allowed_action_kinds:
        # Action kind is not allowed at all: deny before any other gate.
        decision = daapprov.PolicyDecision(
            "deny",
            "safe",
            f'action kind "{action.kind}" is not in the allowlist',
        )
    else:
        # Kind is allowed: run the scope, sensitivity, then mutating gates.
        found: Optional[daapprov.PolicyDecision] = None
        if action.kind == "launch":
            found = _evaluate_launch(
                policy, action, grants, app=app, local_hosts=local_hosts
            )
        if found is None and action.kind in {"fill", "select"}:
            found = _evaluate_fill(policy, action, control, app=app)
        decision = (
            found
            if found is not None
            else _evaluate_mutating(policy, action, digest, app=app)
        )
    return decision
