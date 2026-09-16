import unittest

from migconvert.formats import (
    MAX_SANE_STATEMENT_COUNT,
    FormatError,
    Migration,
    count_statements,
    detect_format,
    parse_dbmate,
    parse_golang_migrate,
    parse_goose,
    render_dbmate,
    render_golang_migrate,
    render_goose,
    statement_count_warnings,
)


class RoundTripTests(unittest.TestCase):
    def test_goose_to_dbmate_and_back(self):
        goose_text = (
            "-- +goose Up\n"
            "CREATE TABLE users (id INTEGER PRIMARY KEY);\n"
            "\n"
            "-- +goose Down\n"
            "DROP TABLE users;\n"
        )
        migration = parse_goose(goose_text)
        migration_back = parse_dbmate(render_dbmate(migration))
        self.assertEqual(migration, migration_back)

    def test_dbmate_to_goose_and_back(self):
        dbmate_text = (
            "-- migrate:up\n"
            "CREATE TABLE users (id INTEGER PRIMARY KEY);\n"
            "\n"
            "-- migrate:down\n"
            "DROP TABLE users;\n"
        )
        migration = parse_dbmate(dbmate_text)
        migration_back = parse_goose(render_goose(migration))
        self.assertEqual(migration, migration_back)

    def test_statement_begin_end_markers_are_dropped_on_conversion(self):
        goose_text = (
            "-- +goose Up\n"
            "-- +goose StatementBegin\n"
            "CREATE FUNCTION noop() RETURNS void AS $$\n"
            "BEGIN\n"
            "END;\n"
            "$$ LANGUAGE plpgsql;\n"
            "-- +goose StatementEnd\n"
            "\n"
            "-- +goose Down\n"
            "DROP FUNCTION noop();\n"
        )
        migration = parse_goose(goose_text)
        self.assertNotIn("StatementBegin", migration.up)
        self.assertNotIn("StatementEnd", migration.up)
        dbmate_text = render_dbmate(migration)
        self.assertEqual(parse_dbmate(dbmate_text).up, migration.up)


class GolangMigrateTests(unittest.TestCase):
    def test_parse_strips_surrounding_blank_lines(self):
        migration = parse_golang_migrate(
            "\nCREATE TABLE users (id INTEGER PRIMARY KEY);\n\n",
            "\n\nDROP TABLE users;\n",
        )
        self.assertEqual(migration.up, "CREATE TABLE users (id INTEGER PRIMARY KEY);")
        self.assertEqual(migration.down, "DROP TABLE users;")

    def test_render_produces_single_trailing_newline_per_file(self):
        migration = Migration(
            up="CREATE TABLE users (id INTEGER PRIMARY KEY);",
            down="DROP TABLE users;",
        )
        up_text, down_text = render_golang_migrate(migration)
        self.assertEqual(up_text, "CREATE TABLE users (id INTEGER PRIMARY KEY);\n")
        self.assertEqual(down_text, "DROP TABLE users;\n")

    def test_render_empty_half_is_empty_file(self):
        up_text, down_text = render_golang_migrate(Migration(up="SELECT 1;", down=""))
        self.assertEqual(down_text, "")

    def test_round_trips_through_goose(self):
        migration = parse_golang_migrate(
            "CREATE TABLE users (id INTEGER PRIMARY KEY);\n", "DROP TABLE users;\n"
        )
        goose_text = render_goose(migration)
        self.assertEqual(parse_goose(goose_text), migration)

    def test_round_trips_from_dbmate(self):
        dbmate_text = (
            "-- migrate:up\n"
            "CREATE TABLE users (id INTEGER PRIMARY KEY);\n"
            "\n"
            "-- migrate:down\n"
            "DROP TABLE users;\n"
        )
        migration = parse_dbmate(dbmate_text)
        up_text, down_text = render_golang_migrate(migration)
        self.assertEqual(parse_golang_migrate(up_text, down_text), migration)


class MalformedInputTests(unittest.TestCase):
    def test_parse_goose_missing_marker(self):
        with self.assertRaises(FormatError):
            parse_goose("CREATE TABLE users (id INTEGER);\n")

    def test_parse_dbmate_missing_marker(self):
        with self.assertRaises(FormatError):
            parse_dbmate("CREATE TABLE users (id INTEGER);\n")

    def test_parse_goose_rejects_dbmate_markers(self):
        with self.assertRaises(FormatError):
            parse_goose("-- migrate:up\nSELECT 1;\n-- migrate:down\nSELECT 1;\n")

    def test_detect_format_unrecognized(self):
        self.assertIsNone(detect_format("CREATE TABLE users (id INTEGER);\n"))

    def test_detect_format_goose(self):
        self.assertEqual(detect_format("-- +goose Up\nSELECT 1;\n"), "goose")

    def test_detect_format_dbmate(self):
        self.assertEqual(detect_format("-- migrate:up\nSELECT 1;\n"), "dbmate")


class CountStatementsTests(unittest.TestCase):
    def test_simple_count(self):
        self.assertEqual(count_statements("SELECT 1; SELECT 2;"), 2)

    def test_trailing_statement_without_semicolon_is_counted(self):
        self.assertEqual(count_statements("SELECT 1"), 1)

    def test_empty_input_counts_zero(self):
        self.assertEqual(count_statements(""), 0)
        self.assertEqual(count_statements("   \n\n  "), 0)

    def test_dollar_quoted_function_body_is_one_statement(self):
        sql = (
            "CREATE FUNCTION noop() RETURNS void AS $$\n"
            "BEGIN\n"
            "  UPDATE t SET x = 1;\n"
            "END;\n"
            "$$ LANGUAGE plpgsql;"
        )
        self.assertEqual(count_statements(sql), 1)

    def test_tagged_dollar_quote_is_one_statement(self):
        sql = "CREATE FUNCTION f() RETURNS int AS $body$SELECT 1;$body$ LANGUAGE sql;"
        self.assertEqual(count_statements(sql), 1)

    def test_semicolon_inside_string_literal_is_not_a_separator(self):
        sql = "INSERT INTO t (name) VALUES ('a;b');"
        self.assertEqual(count_statements(sql), 1)

    def test_semicolon_inside_line_comment_is_not_a_separator(self):
        sql = "-- note: uses a ; in this comment\nSELECT 1;"
        self.assertEqual(count_statements(sql), 1)

    def test_semicolon_inside_block_comment_is_not_a_separator(self):
        sql = "/* a ; in a block comment */\nSELECT 1;"
        self.assertEqual(count_statements(sql), 1)


class StatementCountWarningsTests(unittest.TestCase):
    def test_normal_migration_has_no_warnings(self):
        migration = Migration(up="CREATE TABLE t (id INTEGER);", down="DROP TABLE t;")
        self.assertEqual(statement_count_warnings(migration), [])

    def test_empty_down_has_no_warning(self):
        # A down block with no statements is common for irreversible
        # migrations, so it isn't flagged the way an empty up block is.
        migration = Migration(up="CREATE TABLE t (id INTEGER);", down="")
        self.assertEqual(statement_count_warnings(migration), [])

    def test_empty_up_is_warned(self):
        migration = Migration(up="", down="DROP TABLE t;")
        warnings = statement_count_warnings(migration)
        self.assertEqual(len(warnings), 1)
        self.assertIn("up block has no statements", warnings[0])

    def test_up_over_sanity_bound_is_warned(self):
        up = "SELECT 1;" * (MAX_SANE_STATEMENT_COUNT + 1)
        migration = Migration(up=up, down="SELECT 1;")
        warnings = statement_count_warnings(migration)
        self.assertEqual(len(warnings), 1)
        self.assertIn("up block", warnings[0])
        self.assertIn("sanity bound", warnings[0])

    def test_down_over_sanity_bound_is_warned(self):
        down = "SELECT 1;" * (MAX_SANE_STATEMENT_COUNT + 1)
        migration = Migration(up="SELECT 1;", down=down)
        warnings = statement_count_warnings(migration)
        self.assertEqual(len(warnings), 1)
        self.assertIn("down block", warnings[0])
        self.assertIn("sanity bound", warnings[0])


if __name__ == "__main__":
    unittest.main()
