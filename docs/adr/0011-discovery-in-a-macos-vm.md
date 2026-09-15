# 11. Discovery in a macOS VM

Status: Proposed

## Context

Discovery drives the user's own desktop. It needs Accessibility and
Screen Recording permission on the host. Its reach is bounded by the
policy (allowed apps, URL scope, approvals), but those are checks inside
the agent, not a boundary around it.

Anthropic's computer-use guidance recommends a dedicated virtual machine
or container with minimal privileges. The reference implementation runs
in Docker.

What already limits risk:

- Scope grants are narrowed to the registrable domain, using the public
  suffix list.
- Mutating steps pause for approval, and a submitted mutation is never
  retried.
- Screen content is fenced as untrusted, and credentials only go into
  matching fields.
- A file lock lets one run drive the screen at a time, and runs pause
  while a person uses the Mac.

## Decision

Support running discovery and the live eval tier inside a macOS guest,
documented first and automated later:

- **Guest.** A Tart (or UTM) macOS VM with:
  - its own user and Keychain, holding only the sandbox credentials
  - Accessibility and Screen Recording granted to the Operant driver
  - network limited to the app under test and the model API
- **Driver.** The existing remote driver mode (`operant serve-driver` in
  the guest, `OPERANT_DRIVER__URL=http://...` on the host) keeps the server,
  the evidence and the approvals on the host. Only screen actions run in
  the guest.
- **Lifecycle.** Each run starts from a clean snapshot of the guest and
  discards it afterwards, so a run cannot leave state for the next one.
- **Replay.** Replay of approved capabilities can stay on the host, since
  it runs no model and only follows recorded, approved steps.

## Consequences

- An injected or confused discovery run can only reach the guest.
- macOS licensing allows macOS guests on Apple hardware, which Tart and
  UTM use. Guests need several GB of disk and RAM each.
- Snapshots make live evals repeatable, which ADR 10 needs.

## Alternatives considered

- A separate physical Mac. It isolates just as well, but has no
  snapshots and costs more.
- Docker. Rejected: there is no macOS GUI in containers. Linux apps
  could use the Anthropic reference container, but Operant targets
  macOS apps.
