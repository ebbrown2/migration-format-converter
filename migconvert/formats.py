"""Parsers and renderers for the migration file formats we support.

Both goose and dbmate migrations live in a single .sql file with the up
and down statements separated by a marker comment. The markers differ,
but the underlying shape (an "up" block and a "down" block) is the same,
so a Migration is just those two strings.
"""

import re
from dataclasses import dataclass


class FormatError(Exception):
    """Raised when an input file does not match the expected format."""


@dataclass
class Migration:
    up: str
    down: str


def parse_goose(text: str) -> Migration:
    up_lines = []
    down_lines = []
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-- +goose Up"):
            section = "up"
            continue
        if stripped.startswith("-- +goose Down"):
            section = "down"
            continue
        # StatementBegin/End only matter to goose itself, which uses them to
        # avoid splitting on semicolons inside a statement. We don't split
        # on semicolons at all, so they can be dropped.
        if stripped.startswith("-- +goose StatementBegin"):
            continue
        if stripped.startswith("-- +goose StatementEnd"):
            continue
        if section == "up":
            up_lines.append(line)
        elif section == "down":
            down_lines.append(line)

    if section is None:
        raise FormatError("no '-- +goose Up' marker found")

    return Migration(up="\n".join(up_lines).strip("\n"), down="\n".join(down_lines).strip("\n"))


def parse_dbmate(text: str) -> Migration:
    up_lines = []
    down_lines = []
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-- migrate:up"):
            section = "up"
            continue
        if stripped.startswith("-- migrate:down"):
            section = "down"
            continue
        if section == "up":
            up_lines.append(line)
        elif section == "down":
            down_lines.append(line)

    if section is None:
        raise FormatError("no '-- migrate:up' marker found")

    return Migration(up="\n".join(up_lines).strip("\n"), down="\n".join(down_lines).strip("\n"))


def render_goose(migration: Migration) -> str:
    parts = ["-- +goose Up", migration.up, "", "-- +goose Down", migration.down]
    return "\n".join(parts).rstrip("\n") + "\n"


def render_dbmate(migration: Migration) -> str:
    parts = ["-- migrate:up", migration.up, "", "-- migrate:down", migration.down]
    return "\n".join(parts).rstrip("\n") + "\n"


# Name -> (parse function, render function)
FORMATS = {
    "goose": (parse_goose, render_goose),
    "dbmate": (parse_dbmate, render_dbmate),
}


_DOLLAR_TAG = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


def count_statements(sql: str) -> int:
    """Count top-level statements in a block of SQL.

    A naive `sql.split(";")` overcounts as soon as a statement contains a
    semicolon that isn't a statement separator: inside a string literal, a
    comment, or (the common case for migrations) a `$$`-quoted or
    `$tag$`-quoted function body. This walks the text tracking which of
    those contexts we're in and only counts semicolons seen at top level.
    """
    count = 0
    has_content = False
    dollar_tag = None
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                i += len(dollar_tag)
                dollar_tag = None
                has_content = True
            else:
                i += 1
            continue

        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end + 1
            continue

        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue

        if ch == "'" or ch == '"':
            quote = ch
            i += 1
            while i < n:
                if sql[i] == quote:
                    if sql.startswith(quote * 2, i):
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            has_content = True
            continue

        if ch == "$":
            match = _DOLLAR_TAG.match(sql, i)
            if match:
                dollar_tag = match.group(0)
                i = match.end()
                has_content = True
                continue

        if ch == ";":
            if has_content:
                count += 1
            has_content = False
            i += 1
            continue

        if not ch.isspace():
            has_content = True
        i += 1

    if has_content:
        count += 1
    return count


# Not a hard limit on any of the three tools; just the point past which a
# migration is far more likely to be a missed marker (everything landed in
# one section) than a genuine hand-written batch of statements.
MAX_SANE_STATEMENT_COUNT = 200


def statement_count_warnings(migration: Migration) -> list[str]:
    """Flag statement counts that look like a marker was missed, not a real error.

    These don't affect whether a migration parses; they're surfaced by
    --check as advisory warnings so a caller can decide whether to look
    closer before applying the migration.
    """
    warnings = []
    up_count = count_statements(migration.up)
    down_count = count_statements(migration.down)

    if up_count == 0:
        warnings.append("up block has no statements")
    if up_count > MAX_SANE_STATEMENT_COUNT:
        warnings.append(
            f"up block has {up_count} statements, over the sanity bound of {MAX_SANE_STATEMENT_COUNT}"
        )
    if down_count > MAX_SANE_STATEMENT_COUNT:
        warnings.append(
            f"down block has {down_count} statements, over the sanity bound of {MAX_SANE_STATEMENT_COUNT}"
        )
    return warnings


def detect_format(text: str) -> str | None:
    if "-- +goose Up" in text:
        return "goose"
    if "-- migrate:up" in text:
        return "dbmate"
    return None


def parse_golang_migrate(up_text: str, down_text: str) -> Migration:
    """Build a Migration from the contents of a golang-migrate up/down pair.

    golang-migrate has no marker comments to parse around; the up and down
    halves are already split, one per file, so this just normalizes the
    surrounding blank lines to match what parse_goose/parse_dbmate produce.
    """
    return Migration(up=up_text.strip("\n"), down=down_text.strip("\n"))


def render_golang_migrate(migration: Migration) -> tuple[str, str]:
    """Render a Migration to the (up, down) contents of a golang-migrate pair.

    Returns two strings rather than one, so it can't live in FORMATS
    alongside the marker-based formats, which render a single file.
    """

    def render_half(text: str) -> str:
        return text + "\n" if text else ""

    return render_half(migration.up), render_half(migration.down)
