import argparse
import json
import pathlib
import sys

from . import formats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migconvert",
        description="Convert a SQL migration file between goose and dbmate annotation formats.",
    )
    parser.add_argument(
        "input",
        type=pathlib.Path,
        help="path to the source migration file, or a directory of .sql files",
    )
    parser.add_argument(
        "--from",
        dest="from_format",
        choices=sorted(formats.FORMATS),
        default=None,
        help="source format (auto-detected from markers if omitted)",
    )
    parser.add_argument(
        "--to",
        dest="to_format",
        choices=sorted(formats.FORMATS),
        required=True,
        help="target format",
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

    if args.input.is_dir():
        return _run_directory(args)
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

    sql_files = sorted(p for p in args.input.iterdir() if p.is_file() and p.suffix == ".sql")
    if not sql_files:
        return _fail(args.json, f"no .sql files found in {args.input}")

    args.output.mkdir(parents=True, exist_ok=True)

    results = []
    ok_overall = True
    for path in sql_files:
        result = _convert_one(path, args.from_format, args.to_format, args.output / path.name)
        results.append(result)
        if not result["ok"]:
            ok_overall = False

    if args.json:
        print(json.dumps({"ok": ok_overall, "results": results}))
    else:
        for result in results:
            if result["ok"]:
                print(
                    f"wrote {result['output_file']} "
                    f"({result['from_format']} -> {args.to_format})"
                )
            else:
                print(f"error: {result['input']}: {result['error']}", file=sys.stderr)

    return 0 if ok_overall else 1


def _convert_one(
    path: pathlib.Path,
    from_format_override: str | None,
    to_format: str,
    output_path: pathlib.Path,
) -> dict:
    try:
        text = path.read_text()
    except OSError as exc:
        return {"ok": False, "input": str(path), "error": f"could not read {path}: {exc}"}

    from_format = from_format_override or formats.detect_format(text)
    if from_format is None:
        return {
            "ok": False,
            "input": str(path),
            "error": f"could not detect input format for {path}; pass --from",
        }

    parse_fn, _ = formats.FORMATS[from_format]
    _, render_fn = formats.FORMATS[to_format]

    try:
        migration = parse_fn(text)
    except formats.FormatError as exc:
        return {"ok": False, "input": str(path), "error": str(exc)}

    output_path.write_text(render_fn(migration))

    return {
        "ok": True,
        "input": str(path),
        "output_file": str(output_path),
        "from_format": from_format,
        "to_format": to_format,
        "up_statement_count": formats.count_statements(migration.up),
        "down_statement_count": formats.count_statements(migration.down),
    }


def _fail(as_json: bool, message: str) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": message}))
    else:
        print(f"error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
