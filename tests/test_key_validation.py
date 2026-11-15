"""Key-name validation on the write side.

`set_key` writes ``KEY=value`` verbatim, so a key the reader cannot read back
unchanged produces a line that is silently dropped (`MY KEY=v`, `=v`), read
back under another name (`A=B=v` becomes `A="B=v"`), or split in two
(`A\\nB=v`). These tests pin the writer-side contract for both writer paths:
the CLI `set` command and the library `set_key` function.
"""

import pytest

import dotenv
from dotenv.cli import cli as dotenv_cli

# Keys that are not environment variable names and must be rejected.
INVALID_KEYS = [
    pytest.param("", id="empty"),
    pytest.param("MY KEY", id="space"),
    pytest.param("MY\tKEY", id="tab"),
    pytest.param("A=B", id="equals"),
    pytest.param("1KEY", id="leading-digit"),
    pytest.param("A#B", id="hash"),
    pytest.param("A'B", id="quote"),
    pytest.param("A\nB", id="newline"),
    pytest.param("-A", id="leading-dash"),
    pytest.param("键名", id="non-ascii"),
]

# Keys that must be accepted, written, and read back under the same name.
VALID_KEYS = [
    pytest.param("a", id="single-letter"),
    pytest.param("A", id="single-upper"),
    pytest.param("_", id="single-underscore"),
    pytest.param("_a", id="leading-underscore"),
    pytest.param("a1", id="trailing-digit"),
    pytest.param("a_1_b", id="mixed"),
    pytest.param("PORT", id="upper"),
    pytest.param("__x__", id="dunder"),
    pytest.param("z9", id="short"),
]

# Rejected keys that the reader would additionally mis-read if written verbatim.
SILENTLY_CORRUPTED_KEYS = [
    pytest.param("", id="empty"),
    pytest.param("MY KEY", id="space"),
    pytest.param("MY\tKEY", id="tab"),
    pytest.param("A=B", id="equals"),
    pytest.param("A#B", id="hash"),
    pytest.param("A\nB", id="newline"),
]

# None of the keys under test appear here, so a write appends to this content
# instead of replacing one of its lines.
BEFORE = "# top comment\nX='old' # trailing\nB=\"double\"\nexport C=c\nD=noquote\n"


@pytest.mark.parametrize("key", INVALID_KEYS)
def test_both_writer_paths_reject_invalid_key(cli, dotenv_path, key):
    dotenv_path.write_text(BEFORE)

    with pytest.raises(
        ValueError, match="Invalid environment variable name"
    ) as exc_info:
        dotenv.set_key(dotenv_path, key, "v")

    assert repr(key) in str(exc_info.value)
    assert dotenv_path.read_text() == BEFORE
    assert list(dotenv_path.parent.glob(".tmp_*")) == []

    result = cli.invoke(dotenv_cli, ["--file", str(dotenv_path), "set", "--", key, "v"])

    assert result.exit_code == 2, result.output
    assert result.output.startswith("Error writing env file: ")
    assert "Invalid environment variable name" in result.output
    assert repr(key) in result.output
    assert dotenv_path.read_text() == BEFORE
    assert list(dotenv_path.parent.glob(".tmp_*")) == []


@pytest.mark.parametrize("key", VALID_KEYS)
def test_set_key_accepts_valid_key_and_round_trips(dotenv_path, key):
    dotenv_path.write_text("")

    assert dotenv.set_key(dotenv_path, key, "v") == (True, key, "v")
    dotenv.set_key(dotenv_path, "sentinel", "s")

    # A mis-tokenized key could swallow the line that follows it.
    assert dotenv.get_key(dotenv_path, key) == "v"
    assert dotenv.get_key(dotenv_path, "sentinel") == "s"
    assert list(dotenv.dotenv_values(dotenv_path)) == [key, "sentinel"]


@pytest.mark.parametrize("key", VALID_KEYS)
def test_cli_set_accepts_valid_key_and_round_trips(cli, key):
    result = cli.invoke(dotenv_cli, ["--file", ".env", "set", key, "v"])
    assert (result.exit_code, result.output) == (0, f"{key}=v\n")

    result = cli.invoke(dotenv_cli, ["--file", ".env", "set", "sentinel", "s"])
    assert result.exit_code == 0, result.output

    assert dotenv.dotenv_values(".env") == {key: "v", "sentinel": "s"}


@pytest.mark.parametrize(
    "quote_mode,export",
    [
        ("always", False),
        ("never", False),
        ("auto", False),
        ("always", True),
        ("auto", True),
    ],
)
@pytest.mark.parametrize("key", VALID_KEYS)
def test_writer_paths_produce_identical_output(
    cli, dotenv_path, key, quote_mode, export
):
    value = "a b"
    dotenv_path.write_text(BEFORE)

    dotenv.set_key(dotenv_path, key, value, quote_mode=quote_mode, export=export)
    library_bytes = dotenv_path.read_bytes()
    library_values = dotenv.dotenv_values(dotenv_path)

    dotenv_path.write_text(BEFORE)
    result = cli.invoke(
        dotenv_cli,
        [
            "--file",
            str(dotenv_path),
            "--quote",
            quote_mode,
            "--export",
            str(export).lower(),
            "set",
            key,
            value,
        ],
    )

    assert result.exit_code == 0, result.output
    assert dotenv_path.read_bytes() == library_bytes
    assert dotenv.dotenv_values(dotenv_path) == library_values
    # Existing comments, quotes and `export` prefixes are preserved verbatim.
    assert dotenv_path.read_text().startswith(BEFORE)


@pytest.mark.parametrize("key", VALID_KEYS)
def test_accepted_keys_are_read_back_unchanged(dotenv_path, key):
    dotenv_path.write_text("")

    dotenv.set_key(dotenv_path, key, "v")

    assert list(dotenv.dotenv_values(dotenv_path)) == [key]


@pytest.mark.parametrize("key", SILENTLY_CORRUPTED_KEYS)
def test_reader_drops_or_renames_rejected_keys(dotenv_path, key):
    """The rejected shapes are exactly the ones a raw write would corrupt."""

    dotenv_path.write_text(f"{key}='v'\n")

    assert key not in dotenv.dotenv_values(dotenv_path)
