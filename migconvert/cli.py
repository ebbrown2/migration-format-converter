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
    parser.add_argument("input", type=pathlib.Path, help="path to the source migration file")
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
        help="write converted output here instead of stdout",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of the human-readable summary",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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


def _fail(as_json: bool, message: str) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": message}))
    else:
        print(f"error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
