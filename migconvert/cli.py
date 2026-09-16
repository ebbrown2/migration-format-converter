import argparse
import json
import pathlib
import sys

from . import formats

# golang-migrate splits a migration across two files (<name>.up.sql /
# <name>.down.sql) instead of marking up/down sections inside one file, so
# it can't share the single-text parse/render signature in formats.FORMATS.
# Conversion only runs in directory mode, where a "unit" is a pair of files
# rather than one; --check also accepts a single .up.sql/.down.sql file and
# pairs it with its sibling, since checking doesn't need to write a pair back
# out.
GOLANG_MIGRATE = "golang-migrate"
FORMAT_CHOICES = sorted([*formats.FORMATS, GOLANG_MIGRATE])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migconvert",
        description="Convert a SQL migration file between goose, dbmate, and golang-migrate formats.",
    )
    parser.add_argument(
        "input",
        type=pathlib.Path,
        help=(
            "path to the source migration file, or a directory of migration "
            "files (required for golang-migrate, which pairs .up.sql/.down.sql files)"
        ),
    )
    parser.add_argument(
        "--from",
        dest="from_format",
        choices=FORMAT_CHOICES,
        default=None,
        help="source format (auto-detected from markers if omitted; golang-migrate must be given explicitly)",
    )
    parser.add_argument(
        "--to",
        dest="to_format",
        choices=FORMAT_CHOICES,
        default=None,
        help="target format (required unless --check is given)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate that the input parses without converting or writing anything",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        default=None,
        help=(
            "write converted output here instead of stdout; when the input is a "
            "directory this is the directory converted files are written into, and "
            "is required"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of the human-readable summary",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.check and args.to_format is None:
        return _fail(args.json, "--to is required unless --check is given")

    if args.input.is_dir():
        if args.check:
            return _check_directory(args)
        return _run_directory(args)

    if args.check:
        return _check_file(args)

    if args.from_format == GOLANG_MIGRATE or args.to_format == GOLANG_MIGRATE:
        return _fail(
            args.json,
            "golang-migrate pairs .up.sql/.down.sql files; pass a directory as input",
        )
    return _run_file(args)


def _run_file(args: argparse.Namespace) -> int:
    try:
        text = args.input.read_text()
    except OSError as exc:
        return _fail(args.json, f"could not read {args.input}: {exc}")

    from_format = args.from_format or formats.detect_format(text)
    if from_format is None:
        return _fail(args.json, f"could not detect input format for {args.input}; pass --from")

    parse_fn, _ = formats.FORMATS[from_format]
    _, render_fn = formats.FORMATS[args.to_format]

    try:
        migration = parse_fn(text)
    except formats.FormatError as exc:
        return _fail(args.json, str(exc))

    output = render_fn(migration)

    if args.output is not None:
        args.output.write_text(output)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "input": str(args.input),
                    "from_format": from_format,
                    "to_format": args.to_format,
                    "output_file": str(args.output) if args.output else None,
                    "up_statement_count": formats.count_statements(migration.up),
                    "down_statement_count": formats.count_statements(migration.down),
                    "output": None if args.output else output,
                }
            )
        )
    elif args.output is not None:
        print(f"wrote {args.output} ({from_format} -> {args.to_format})")
    else:
        sys.stdout.write(output)

    return 0


def _run_directory(args: argparse.Namespace) -> int:
    if args.output is None:
        return _fail(args.json, "--output directory is required when input is a directory")
    if args.output.exists() and not args.output.is_dir():
        return _fail(args.json, f"{args.output} exists and is not a directory")

    if args.from_format == GOLANG_MIGRATE:
        units, error = _collect_golang_migrate_pairs(args.input)
    else:
        units, error = _collect_single_file_units(args.input)
    if error:
        return _fail(args.json, error)

    args.output.mkdir(parents=True, exist_ok=True)

    results = []
    ok_overall = True
    for unit in units:
        result = _convert_unit(unit, args.from_format, args.to_format, args.output)
        results.append(result)
        if not result["ok"]:
            ok_overall = False

    if args.json:
        print(json.dumps({"ok": ok_overall, "results": results}))
    else:
        for result in results:
            if result["ok"]:
                written = " and ".join(result["output_files"]) if result["output_files"] else result["output_file"]
                print(f"wrote {written} ({result['from_format']} -> {args.to_format})")
            else:
                print(f"error: {result['input']}: {result['error']}", file=sys.stderr)

    return 0 if ok_overall else 1


def _check_file(args: argparse.Namespace) -> int:
    if args.from_format == GOLANG_MIGRATE:
        if not _is_golang_migrate_half(args.input):
            return _fail(
                args.json,
                f"{args.input} is not a .up.sql/.down.sql file; golang-migrate needs "
                "one of those, or a directory, as input",
            )
        return _check_golang_migrate_file(args)
    if args.from_format is None and _is_golang_migrate_half(args.input):
        return _check_golang_migrate_file(args)

    try:
        text = args.input.read_text()
    except OSError as exc:
        return _fail(args.json, f"could not read {args.input}: {exc}")

    from_format = args.from_format or formats.detect_format(text)
    if from_format is None:
        return _fail(args.json, f"could not detect input format for {args.input}; pass --from")

    parse_fn, _ = formats.FORMATS[from_format]
    try:
        migration = parse_fn(text)
    except formats.FormatError as exc:
        return _fail(args.json, str(exc))

    up_count = formats.count_statements(migration.up)
    down_count = formats.count_statements(migration.down)
    warnings = formats.statement_count_warnings(migration)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "input": str(args.input),
                    "from_format": from_format,
                    "up_statement_count": up_count,
                    "down_statement_count": down_count,
                    "warnings": warnings,
                }
            )
        )
    else:
        print(f"ok: {args.input} ({from_format}, {up_count} up / {down_count} down statements)")
        for warning in warnings:
            print(f"warning: {args.input}: {warning}", file=sys.stderr)

    return 0


def _is_golang_migrate_half(path: pathlib.Path) -> bool:
    return path.name.endswith(".up.sql") or path.name.endswith(".down.sql")


def _golang_migrate_peer_paths(
    path: pathlib.Path,
) -> tuple[str, pathlib.Path | None, pathlib.Path | None]:
    """Given one half of a golang-migrate pair, find the other half beside it."""
    if path.name.endswith(".up.sql"):
        stem = path.name[: -len(".up.sql")]
        up_path, down_path = path, path.with_name(f"{stem}.down.sql")
    else:
        stem = path.name[: -len(".down.sql")]
        up_path, down_path = path.with_name(f"{stem}.up.sql"), path

    return stem, (up_path if up_path.exists() else None), (down_path if down_path.exists() else None)


def _check_golang_migrate_file(args: argparse.Namespace) -> int:
    if not args.input.exists():
        return _fail(args.json, f"could not read {args.input}: No such file or directory")

    name, up_path, down_path = _golang_migrate_peer_paths(args.input)
    unit = {"name": name, "up_path": up_path, "down_path": down_path}
    result = _check_unit(unit, GOLANG_MIGRATE)

    if args.json:
        print(json.dumps(result))
    elif result["ok"]:
        print(
            f"ok: {result['input']} ({result['from_format']}, "
            f"{result['up_statement_count']} up / {result['down_statement_count']} down statements)"
        )
        for warning in result["warnings"]:
            print(f"warning: {result['input']}: {warning}", file=sys.stderr)
    else:
        print(f"error: {result['input']}: {result['error']}", file=sys.stderr)

    return 0 if result["ok"] else 1


def _check_directory(args: argparse.Namespace) -> int:
    if args.from_format == GOLANG_MIGRATE:
        units, error = _collect_golang_migrate_pairs(args.input)
    else:
        units, error = _collect_single_file_units(args.input)
    if error:
        return _fail(args.json, error)

    results = [_check_unit(unit, args.from_format) for unit in units]
    ok_overall = all(result["ok"] for result in results)

    if args.json:
        print(json.dumps({"ok": ok_overall, "results": results}))
    else:
        for result in results:
            if result["ok"]:
                print(
                    f"ok: {result['input']} ({result['from_format']}, "
                    f"{result['up_statement_count']} up / {result['down_statement_count']} down statements)"
                )
                for warning in result["warnings"]:
                    print(f"warning: {result['input']}: {warning}", file=sys.stderr)
            else:
                print(f"error: {result['input']}: {result['error']}", file=sys.stderr)

    return 0 if ok_overall else 1


def _check_unit(unit: dict, from_format_override: str | None) -> dict:
    migration, from_format, error = _load_migration(unit, from_format_override)
    if error:
        return {"ok": False, "input": _unit_input_desc(unit), "error": error}
    return {
        "ok": True,
        "input": _unit_input_desc(unit),
        "from_format": from_format,
        "up_statement_count": formats.count_statements(migration.up),
        "down_statement_count": formats.count_statements(migration.down),
        "warnings": formats.statement_count_warnings(migration),
    }


def _collect_single_file_units(input_dir: pathlib.Path) -> tuple[list[dict], str | None]:
    # .up.sql/.down.sql files belong to a golang-migrate pair, not a
    # standalone goose/dbmate file; skip them so a mixed directory doesn't
    # get half its files misread as malformed single-file migrations.
    sql_files = sorted(
        p
        for p in input_dir.iterdir()
        if p.is_file()
        and p.suffix == ".sql"
        and not p.name.endswith(".up.sql")
        and not p.name.endswith(".down.sql")
    )
    if not sql_files:
        return [], f"no .sql files found in {input_dir}"
    return [{"name": p.stem, "path": p} for p in sql_files], None


def _collect_golang_migrate_pairs(input_dir: pathlib.Path) -> tuple[list[dict], str | None]:
    up_paths: dict[str, pathlib.Path] = {}
    down_paths: dict[str, pathlib.Path] = {}
    for path in input_dir.iterdir():
        if not path.is_file():
            continue
        if path.name.endswith(".up.sql"):
            up_paths[path.name[: -len(".up.sql")]] = path
        elif path.name.endswith(".down.sql"):
            down_paths[path.name[: -len(".down.sql")]] = path

    names = sorted(set(up_paths) | set(down_paths))
    if not names:
        return [], f"no .up.sql/.down.sql pairs found in {input_dir}"
    return [
        {"name": name, "up_path": up_paths.get(name), "down_path": down_paths.get(name)}
        for name in names
    ], None


def _load_migration(
    unit: dict, from_format_override: str | None
) -> tuple[formats.Migration | None, str | None, str | None]:
    """Read a unit's source file(s) and parse them into a Migration.

    Returns (migration, from_format, error); exactly one of migration/error
    is set on return.
    """
    if "path" in unit:
        path = unit["path"]
        try:
            text = path.read_text()
        except OSError as exc:
            return None, None, f"could not read {path}: {exc}"

        from_format = from_format_override or formats.detect_format(text)
        if from_format is None:
            return None, None, f"could not detect input format for {path}; pass --from"
        if from_format == GOLANG_MIGRATE:
            return None, None, f"{path} is a single file; golang-migrate needs a .up.sql/.down.sql pair"

        parse_fn, _ = formats.FORMATS[from_format]
        try:
            migration = parse_fn(text)
        except formats.FormatError as exc:
            return None, from_format, str(exc)
        return migration, from_format, None

    up_path, down_path = unit["up_path"], unit["down_path"]
    if up_path is None:
        return None, None, f"missing {unit['name']}.up.sql"
    if down_path is None:
        return None, None, f"missing {unit['name']}.down.sql"
    try:
        up_text = up_path.read_text()
        down_text = down_path.read_text()
    except OSError as exc:
        return None, None, f"could not read migration files: {exc}"
    return formats.parse_golang_migrate(up_text, down_text), GOLANG_MIGRATE, None


def _write_migration(
    migration: formats.Migration, to_format: str, output_dir: pathlib.Path, name: str
) -> list[pathlib.Path]:
    if to_format == GOLANG_MIGRATE:
        up_text, down_text = formats.render_golang_migrate(migration)
        up_path = output_dir / f"{name}.up.sql"
        down_path = output_dir / f"{name}.down.sql"
        up_path.write_text(up_text)
        down_path.write_text(down_text)
        return [up_path, down_path]

    _, render_fn = formats.FORMATS[to_format]
    output_path = output_dir / f"{name}.sql"
    output_path.write_text(render_fn(migration))
    return [output_path]


def _unit_input_desc(unit: dict) -> str:
    if "path" in unit:
        return str(unit["path"])
    known = unit["up_path"] or unit["down_path"]
    return str(known.parent / f"{unit['name']}.{{up,down}}.sql")


def _convert_unit(
    unit: dict,
    from_format_override: str | None,
    to_format: str,
    output_dir: pathlib.Path,
) -> dict:
    migration, from_format, error = _load_migration(unit, from_format_override)
    if error:
        return {"ok": False, "input": _unit_input_desc(unit), "error": error}

    output_paths = _write_migration(migration, to_format, output_dir, unit["name"])

    result = {
        "ok": True,
        "input": _unit_input_desc(unit),
        "from_format": from_format,
        "to_format": to_format,
        "up_statement_count": formats.count_statements(migration.up),
        "down_statement_count": formats.count_statements(migration.down),
    }
    if len(output_paths) == 1:
        result["output_file"] = str(output_paths[0])
        result["output_files"] = None
    else:
        result["output_file"] = None
        result["output_files"] = [str(p) for p in output_paths]
    return result


def _fail(as_json: bool, message: str) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": message}))
    else:
        print(f"error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
