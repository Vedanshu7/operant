# 13. Screen identity and UI drift

Status: Accepted (implemented)

## Context

`locate` took the best whole-screen score. Real runs showed the cost:

- 13 replays matched `accounts-overview` on a logged-in home page. 2 failed
  because of it. 5 more were extraction misses reported under the same class.
- Only 1 of 8 stored nodes had a fingerprint.
- `merge` keyed nodes on title alone, undoing the recorder's split of two
  states that share a title.
- A fingerprint is an exact list, so a UI change could erase it.

Evidence:

- Whole-page comparison cannot reliably identify near-duplicates.
- Under-merging produced 3,774 states against 27, and over-merging ended
  exploration early, so strictness alone is not the goal.
- Similo weights attributes by stability, and CALM reuses what stayed the same
  across versions.

## Decision

### Say how sure the match is

`locate` returns `match`, `drifted`, `ambiguous` or `unknown`.

- `match`: one node, checks hold, the URL agrees. The only result that gives
  discovery a hint or lets replay trust a route without a hop.
- `drifted`: one node, but the checks or URL disagree, or the checks hold while
  both views fail. Replay tries the existing hop, else follows the recorded
  path.
- `ambiguous` and `unknown`: no guess. An expected node from the path can settle
  a tie, and nothing else.

### Two views of identity

- Text is `role|name`. Structure is `role|coarse_path`. The label is left out,
  because it is only the text before the control.
- Each view keeps what is unique to a node, derived when matching so a stored
  copy cannot go stale.
- The winner has the most hits across both views, strictly more than any rival.
- Identity needs every live node to have a fingerprint. A node with no
  fingerprint and no live edge is ignored. Otherwise whole-fingerprint coverage
  runs, then the checks.
- A node with no unique signatures falls back to coverage too.

### URL

`ScreenDigest.url` comes from AppleScript, because `xa11y` exposes no address.
AppleScript finds an app by name, which can be the person's own browser, so it
asks for the window with the bound title. A page sets its own title, so the
title is an argument and never part of the script. The address is reduced to a value-free path, stored on `Node.url_paths`, and can only
veto a match, since index pages repeat across login states.

### When the UI changes

- Translation breaks text and keeps structure. A redesign does the reverse.
  Identity survives either.
- Both failing means `unknown`, or `drifted` if the checks still hold.
- A verified arrival that lost a view emits `screen_drifted`, and the success
  counts against stability, so three in a row degrade an approved capability.
- `operant graph learn <vendor>` intersects at least 3 verified visits into a
  stable core and saves a new version. It runs only on command, so one banner
  cannot enter an identity.
- Visits count from any graph version whose checks for that node match, because
  capabilities replay on pinned versions. Walking back from the newest visit
  stops where the look changes, so a redesign needs 3 visits of its own.
- A URL path needs 3 visits too.
- `operant catalog repin <id>` moves a capability to another version, or refuses
  and names what's missing. It becomes a draft and starts a new track record,
  because a different graph is a different thing to trust.

### When identity is not enough

Two states can match down to their fingerprints: a home page before and after
login shares 90% of its controls. So replay also checks that the next recorded
step's control is on screen. If it isn't, the run is further along than the path
assumes, and replay clicks the live link to the furthest step it can name. A link
counts only if its name is unique to that node's title, so a logo link named
after the app doesn't. Discovery can still get a hint for such a page, but it only
advises and the model sees the screen.

### Merge

Nodes key on title plus content. A node with no fingerprint takes one only from
a recording that leaves it the same way.

## Consequences

- Graphs reach full identity only after screens are re-recorded or learned.
  Until then behaviour matches coverage and checks.
- A logged-in home page needs its own recorded node before identity can
  separate it.
- URL capture triggers the macOS Automation prompt. Its per-snapshot cost has
  not been measured live.

## Alternatives considered

- A hash per screen. Rejected: one extra control changes it.
- Embeddings or screenshot hashes. Rejected: a model dependency, and ADR 5
  already prefers deterministic matching.
- Variant lists per node. Deferred until real A/B pages appear.
