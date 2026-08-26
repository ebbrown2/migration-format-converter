# migconvert

Converts a single SQL migration file between two annotation styles:

- **goose**: `-- +goose Up` / `-- +goose Down` (optionally wrapped in
  `-- +goose StatementBegin` / `-- +goose StatementEnd`)
- **dbmate**: `-- migrate:up` / `-- migrate:down`

Both tools store an "up" and a "down" block in one `.sql` file; they just
disagree on the marker comments. If you're moving a project from one
migration tool to the other, you end up hand-editing every file in your
migrations directory. This does that mechanically.

## Usage

```
$ cat 0001_create_users.sql
-- +goose Up
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL
);

-- +goose Down
DROP TABLE users;

$ python -m migconvert 0001_create_users.sql --to dbmate
-- migrate:up
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL
);

-- migrate:down
DROP TABLE users;
```

The source format is auto-detected from the markers present in the file.
Pass `--from goose` or `--from dbmate` explicitly if a file happens to be
ambiguous (for example, an empty migration with no markers at all).

Write the result to a file instead of stdout:

```
$ python -m migconvert 0001_create_users.sql --to dbmate -o db/migrations/20260827120000_create_users.sql
wrote db/migrations/20260827120000_create_users.sql (goose -> dbmate)
```

## JSON output

Every command supports `--json` for scripting against, which reports the
detected format and statement counts instead of (or alongside) the
converted SQL:

```
$ python -m migconvert 0001_create_users.sql --to dbmate --json
{"ok": true, "input": "0001_create_users.sql", "from_format": "goose", "to_format": "dbmate", "output_file": null, "up_statement_count": 1, "down_statement_count": 1, "output": "-- migrate:up\nCREATE TABLE users (...);\n\n-- migrate:down\nDROP TABLE users;\n"}
```

When `-o/--output` is also given, `"output"` is `null` in the JSON (the
SQL went to the file, not stdout) and `"output_file"` names where it was
written. On failure the JSON is `{"ok": false, "error": "..."}` and the
exit code is 1.

## Status

Early skeleton. Handles the common case (one up block, one down block,
no nested `$$`-quoted function bodies). See the tracker in this repo for
what's not handled yet.

## License

MIT, see LICENSE.
