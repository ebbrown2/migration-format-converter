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


def detect_format(text: str) -> str | None:
    if "-- +goose Up" in text:
        return "goose"
    if "-- migrate:up" in text:
        return "dbmate"
    return None
