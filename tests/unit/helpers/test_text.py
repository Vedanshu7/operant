import operant.helpers.ids as ids
import operant.helpers.text as text


def test_slugify_and_safe_filename() -> None:
    assert text.slugify("ParaBank | Accounts Overview") == (
        "parabank-accounts-overview"
    )
    assert text.slugify("!!!") == "untitled"
    assert text.slugify("a" * 100, max_length=5) == "aaaaa"
    assert text.safe_filename("failure edge-3/2") == "failure-edge-3-2"


def test_truncate_and_placeholders() -> None:
    assert text.truncate("hello", 10) == "hello"
    assert text.truncate("hello world", 6) == "hello…"
    assert (
        text.substitute_placeholders(
            "acct {{accountId}} {{missing}}", {"accountId": "12456"}
        )
        == "acct 12456 {{missing}}"
    )


def test_ids_are_prefixed_and_unique() -> None:
    first, second = ids.run_id("replay"), ids.run_id("replay")
    assert first.startswith("replay-") and first != second
    assert ids.short_id("iv").startswith("iv-")
    assert len(ids.nonce()) >= 16
