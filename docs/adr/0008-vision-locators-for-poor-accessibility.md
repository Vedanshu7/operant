# 8. Vision locators for apps with poor accessibility

Status: Proposed

## Context

Replay finds every target through the accessibility (AX) tree:

- Each recorded step stores a ranked stack: role and name, label
  proximity, tree path, and a region. Even the region strategy needs an AX
  role (`domain/models/targets.py`).
- Screens are recognized by fingerprints built from AX controls
  (`domain/fingerprint.py`).

Some apps give an empty or useless tree:

- canvas apps
- Citrix, VDI and other remote desktops
- some Java and Electron apps

Discovery can still click by coordinates from the screenshot, but replay
then has nothing to locate with and escalates on every run. Banks, the
target domain, often run apps through Citrix.

Evidence:

- UGround, OmniParser, UI-TARS and Aguvis show pixel-only grounding
  matching or beating agents given AX or HTML text.
- ScreenSpot-Pro shows grounding drops on large, dense screens, and
  recovers when the search is narrowed to a region.
- The replay robustness suite (`tests/evals/perturb.py`, README) shows
  the AX stack absorbs renames, reorders, banners and moves without
  acting on the wrong control. The gap is apps with no tree, not apps
  whose tree changes.

## Decision

Two steps, so the cost is paid only where the tree is poor.

### 1. Measure accessibility quality per capability (first)

- At compile time, compute an AX-quality score from the recording:
  - the share of steps recorded as coordinate clicks
  - the share of targets with an empty name and label
  - the share of screens whose fingerprint has fewer than 3 controls
- Store it on the artifact and show it in the catalog and the UI.
- Below a threshold, warn at approval time: "this capability depends on
  screen positions and will break when the layout changes".

### 2. Add a vision strategy where the score is low (later)

- A new `VisualStrategy` in the target stack, after the AX strategies:
  - an image crop of the target, recorded at discovery
  - its OCR text
  - an offset from a stable visual landmark (a logo, a heading)
- At replay it is matched by template search within a region around the
  recorded position (the ScreenSpot-Pro lesson), and accepted only above
  a similarity threshold.
- Screens with a weak AX fingerprint also get an OCR text fingerprint.
- The same rules apply as for other strategies: a match that is not
  unique escalates, and mutating steps keep their approval gate.

## Consequences

- Capabilities on AX-poor apps become replayable, with an honest
  brittleness score.
- Recorded crops are screenshots: they go through the same masking
  (`helpers/images.black_out`) and retention as evidence.
- Template matching is sensitive to themes and scaling. Replay pins the
  window size and display scale it recorded, or fails closed when they
  differ (review item 5.2).

## Alternatives considered

- A grounding model at replay (UI-TARS, OmniParser). Rejected as the
  default: it brings a model back into replay, with its cost, latency and
  injection surface. It stays an option for the opt-in heal step
  (ADR 9).
- Recording coordinates only. That is what happens today, and it fails
  on any reflow.
