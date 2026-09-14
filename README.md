# migconvert

Converts SQL migration files between three tools' conventions:

- **goose**: `-- +goose Up` / `-- +goose Down` (optionally wrapped in
  `-- +goose StatementBegin` / `-- +goose StatementEnd`), one `.sql` file
- **dbmate**: `-- migrate:up` / `-- migrate:down`, one `.sql` file
- **golang-migrate**: no markers; up and down live in separate
  `<name>.up.sql` / `<name>.down.sql` files

goose and dbmate store an "up" and a "down" block in one file and just
disagree on the marker comments; golang-migrate splits them across two
files instead. If you're moving a project from one migration tool to
another, you end up hand-editing every file in your migrations directory.
This does that mechanically.

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

## Directory mode

Pass a directory as the input to convert every `.sql` file in it. `-o` is
required in this case and names the directory converted files are written
into (it's created if it doesn't exist); each file keeps its original name.
Source format is auto-detected per file unless `--from` is given, in which
case it's applied to every file in the directory.

```
$ python -m migconvert db/goose_migrations --to dbmate -o db/migrations
wrote db/migrations/0001_create_users.sql (goose -> dbmate)
wrote db/migrations/0002_add_index.sql (goose -> dbmate)
```

A file that fails to parse is reported and does not stop the rest of the
batch; the command exits 1 if any file failed. With `--json`, the result
is `{"ok": bool, "results": [...]}` where each entry has the same shape as
the single-file JSON output (or `{"ok": false, "input": ..., "error": ...}`
for a failed file).

### golang-migrate

golang-migrate has no marker comments, so it only works in directory mode,
where each migration is a `<name>.up.sql` / `<name>.down.sql` pair rather
than a single file:

```
$ ls db/goose_migrations
0001_create_users.sql
$ python -m migconvert db/goose_migrations --to golang-migrate -o db/migrations
wrote db/migrations/0001_create_users.up.sql and db/migrations/0001_create_users.down.sql (goose -> golang-migrate)
```

Converting the other direction requires `--from golang-migrate` explicitly
(the source format can't be auto-detected from file contents the way the
marker-based formats can):

```
$ ls db/migrations
0001_create_users.up.sql
0001_create_users.down.sql
$ python -m migconvert db/migrations --from golang-migrate --to dbmate -o db/dbmate_migrations
wrote db/dbmate_migrations/0001_create_users.sql (golang-migrate -> dbmate)
```

A pair missing one half (an `.up.sql` with no matching `.down.sql`, or vice
versa) is reported as an error for that migration and doesn't stop the rest
of the batch, same as a malformed file in the marker-based formats.

In the JSON output, a result whose target is golang-migrate has
`"output_file": null` and `"output_files": [...]` (a two-element list)
instead; every other result keeps `"output_file"` and has
`"output_files": null`.

## Check mode

Pass `--check` to validate that a file (or every file in a directory) parses
without converting or writing anything. `--to` isn't needed in this mode
since there's no target format; `-o/--output` is ignored if given.

```
$ python -m migconvert 0001_create_users.sql --check
ok: 0001_create_users.sql (goose, 1 up / 1 down statements)
```

Directory mode reports one line per file (or `--json` result entry) and
exits 1 if any file fails to parse, the same as conversion:

```
$ python -m migconvert db/goose_migrations --check
ok: db/goose_migrations/0001_create_users.sql (goose, 1 up / 1 down statements)
error: db/goose_migrations/0002_broken.sql: no '-- +goose Up' marker found
```

golang-migrate directories need `--from golang-migrate`, same as
conversion, since it can't be auto-detected from a lone file's contents.

`--check` also accepts a single `.up.sql` or `.down.sql` file directly
(conversion doesn't, since writing a pair back out needs a directory to put
both files in). The missing half is found beside it and both are checked
together as one migration:

```
$ python -m migconvert db/migrations/0001_create_users.up.sql --check
ok: db/migrations/0001_create_users.{up,down}.sql (golang-migrate, 1 up / 1 down statements)
```

If the sibling file doesn't exist, this is reported the same as a missing
half in directory mode. `--from golang-migrate` is only required here if
the file's name doesn't end in `.up.sql`/`.down.sql`.

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

## Tests

```
$ python -m unittest discover -s tests
```

No third-party test runner required; the suite uses `unittest` from the
standard library and covers goose/dbmate round-trip conversion, malformed
input, and the statement counter's handling of `$$`-quoted bodies,
string literals, and comments.

## Status

Early skeleton. Handles the common case (one up block, one down block).
The `--json` statement counts account for `$$`- and `$tag$`-quoted
function bodies, so a semicolon inside a `CREATE FUNCTION` body doesn't
get counted as a statement separator.

## License

MIT, see LICENSE.
