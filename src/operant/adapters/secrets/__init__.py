"""Secret store backends: environment, macOS Keychain, and a chain of both.

Typical usage example:

  store = factory.secret_store(settings.secrets)
  value = store.get("PARABANK_PASSWORD")
"""
