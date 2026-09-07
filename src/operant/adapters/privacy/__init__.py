"""
PII scrubbers: Presidio (local NLP + patterns) and a no-op fallback.

Typical usage example:

  scrubber = factory.scrubber(settings.privacy)
  safe = scrubber.scrub(digest_text)
"""
