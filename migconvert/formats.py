"""Parsers and renderers for the migration file formats we support.

Both goose and dbmate migrations live in a single .sql file with the up
and down statements separated by a marker comment. The markers differ,
but the underlying shape (an "up" block and a "down" block) is the same,
so a Migration is just those two strings.
"""

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


def detect_format(text: str) -> str | None:
    if "-- +goose Up" in text:
        return "goose"
    if "-- migrate:up" in text:
        return "dbmate"
    return None
