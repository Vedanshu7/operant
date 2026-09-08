# 7. Local PII scrubbing with Presidio

Status: Accepted (implemented)

## Context

Two mechanisms protect data today:

- `Redactor` masks exact values it was told about: secrets, plus inputs and
  outputs classified as sensitive.
- `sensitivity.classify` spots sensitive values by field name and shape
  (card numbers with a Luhn check, IBAN, SSN, email, phone). It feeds the
  approval gates. It does not redact text.

Neither catches unknown PII in free text, such as a customer's name,
address, or date of birth on screen. That text will now flow to more places:
Langfuse (ADR 2), memory (ADR 5), and the planner and verifier (ADR 3).

## Decision

Add a local PII scrubber built on Microsoft Presidio, layered after the
exact redactor.

- A new port `TextScrubber` with one method, `scrub(text)`.
- The adapter uses `presidio-analyzer` and `presidio-anonymizer` with a
  spaCy model (default `en_core_web_lg`). Everything runs locally.
- Built-in recognizers: card number, IBAN, SSN, email, phone, person,
  location, date, bank number.
- Custom recognizers reuse the patterns in `sensitivity`, so both layers
  agree.
- Found entities become typed placeholders such as `<PERSON>`.
- A no-op scrubber is used when the optional `privacy` extra is not
  installed.
- `operant doctor` checks that the spaCy model is present.

Where each layer applies:

| Destination | Exact redactor | Presidio |
|---|---|---|
| Executor model | Secrets only (as today) | No |
| Planner and verifier | Yes | Yes |
| Langfuse | Yes | Yes |
| Memory tables | Yes | Yes |
| Evidence log and live events | Yes (as today) | Opt-in |

The executor is not scrubbed. It must read real labels and values to click
the right control. It still never sees secret values.

## Consequences

- Unknown PII is masked before it leaves the process or is stored.
- The spaCy model is large (about 500 MB for `en_core_web_lg`). It is
  optional and configurable.
- Presidio can mask too much, for example a product name read as a person.
  This is acceptable for traces and memory, which is why the executor is
  left out.

## Alternatives considered

- Regex only. Rejected: misses names and addresses.
- A cloud DLP service. Rejected: the text would leave the machine to be
  scrubbed.

## Implementation notes

- Code: `ports/privacy.py`, `adapters/privacy/` (Presidio, no-op,
  factory). Optional extra: `privacy`; the spaCy model is installed
  separately (see the README) or via the Docker build args.
- Evidence scrubbing scrubs string values after exact redaction, never the
  JSON text, so a match cannot break the structure.
- The small spaCy model masks some UI labels as `<PERSON>`; this is why
  the executor is never scrubbed.
