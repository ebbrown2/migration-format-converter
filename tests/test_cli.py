import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from migconvert.cli import main


class GolangMigrateDirectoryTests(unittest.TestCase):
    def test_goose_to_golang_migrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dest = Path(tmp) / "dest"
            src.mkdir()
            (src / "0001_create_users.sql").write_text(
                "-- +goose Up\n"
                "CREATE TABLE users (id INTEGER PRIMARY KEY);\n"
                "\n"
                "-- +goose Down\n"
                "DROP TABLE users;\n"
            )

            exit_code = main([str(src), "--to", "golang-migrate", "-o", str(dest)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                (dest / "0001_create_users.up.sql").read_text(),
                "CREATE TABLE users (id INTEGER PRIMARY KEY);\n",
            )
            self.assertEqual(
                (dest / "0001_create_users.down.sql").read_text(), "DROP TABLE users;\n"
            )

    def test_golang_migrate_to_dbmate(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dest = Path(tmp) / "dest"
            src.mkdir()
            (src / "0001_create_users.up.sql").write_text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY);\n"
            )
            (src / "0001_create_users.down.sql").write_text("DROP TABLE users;\n")

            exit_code = main(
                [str(src), "--from", "golang-migrate", "--to", "dbmate", "-o", str(dest)]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                (dest / "0001_create_users.sql").read_text(),
                "-- migrate:up\nCREATE TABLE users (id INTEGER PRIMARY KEY);\n\n"
                "-- migrate:down\nDROP TABLE users;\n",
            )

    def test_incomplete_pair_reports_error_without_stopping_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dest = Path(tmp) / "dest"
            src.mkdir()
            (src / "0001_create_users.up.sql").write_text("CREATE TABLE users (id INTEGER);\n")
            # no 0001_create_users.down.sql
            (src / "0002_add_index.up.sql").write_text("CREATE INDEX idx ON users (id);\n")
            (src / "0002_add_index.down.sql").write_text("DROP INDEX idx;\n")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        str(src),
                        "--from",
                        "golang-migrate",
                        "--to",
                        "dbmate",
                        "-o",
                        str(dest),
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            results_by_input = {r["input"]: r for r in payload["results"]}
            failed = next(r for r in payload["results"] if not r["ok"])
            self.assertIn("down.sql", failed["error"])
            self.assertTrue((dest / "0002_add_index.sql").exists())
            self.assertEqual(len(results_by_input), 2)

    def test_golang_migrate_output_uses_output_files_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dest = Path(tmp) / "dest"
            src.mkdir()
            (src / "0001_create_users.sql").write_text(
                "-- migrate:up\nCREATE TABLE users (id INTEGER);\n\n-- migrate:down\nDROP TABLE users;\n"
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main([str(src), "--to", "golang-migrate", "-o", str(dest), "--json"])

            result = json.loads(stdout.getvalue())["results"][0]
            self.assertIsNone(result["output_file"])
            self.assertEqual(len(result["output_files"]), 2)

    def test_single_file_input_with_golang_migrate_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "0001_create_users.sql"
            src.write_text("-- +goose Up\nSELECT 1;\n\n-- +goose Down\nSELECT 1;\n")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main([str(src), "--to", "golang-migrate"])

            self.assertEqual(exit_code, 1)
            self.assertIn("golang-migrate", stderr.getvalue())


class CheckModeTests(unittest.TestCase):
    def test_check_valid_file_does_not_require_to(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "0001_create_users.sql"
            src.write_text("-- +goose Up\nSELECT 1;\n\n-- +goose Down\nSELECT 2;\n")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main([str(src), "--check", "--json"])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["from_format"], "goose")
            self.assertEqual(payload["up_statement_count"], 1)
            self.assertEqual(payload["down_statement_count"], 1)
            self.assertNotIn("output", payload)

    def test_check_does_not_write_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "0001_create_users.sql"
            src.write_text("-- +goose Up\nSELECT 1;\n\n-- +goose Down\nSELECT 2;\n")
            out = Path(tmp) / "out.sql"

            exit_code = main([str(src), "--check", "-o", str(out)])

            self.assertEqual(exit_code, 0)
            self.assertFalse(out.exists())

    def test_check_malformed_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "bad.sql"
            src.write_text("SELECT 1;\n")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main([str(src), "--check"])

            self.assertEqual(exit_code, 1)
            self.assertIn("no", stderr.getvalue())

    def test_check_without_to_or_check_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "0001_create_users.sql"
            src.write_text("-- +goose Up\nSELECT 1;\n\n-- +goose Down\nSELECT 2;\n")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main([str(src)])

            self.assertEqual(exit_code, 1)
            self.assertIn("--to", stderr.getvalue())

    def test_check_golang_migrate_single_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "0001_create_users.sql"
            src.write_text("-- +goose Up\nSELECT 1;\n\n-- +goose Down\nSELECT 2;\n")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main([str(src), "--check", "--from", "golang-migrate"])

            self.assertEqual(exit_code, 1)
            self.assertIn("directory", stderr.getvalue())

    def test_check_directory_reports_each_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "0001_create_users.sql").write_text(
                "-- +goose Up\nSELECT 1;\n\n-- +goose Down\nSELECT 2;\n"
            )
            (src / "0002_bad.sql").write_text("SELECT 1;\n")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main([str(src), "--check", "--json"])

            self.assertEqual(exit_code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            results_by_input = {Path(r["input"]).name: r for r in payload["results"]}
            self.assertTrue(results_by_input["0001_create_users.sql"]["ok"])
            self.assertFalse(results_by_input["0002_bad.sql"]["ok"])

    def test_check_golang_migrate_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "0001_create_users.up.sql").write_text("SELECT 1;\n")
            # no matching down file

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [str(src), "--check", "--from", "golang-migrate", "--json"]
                )

            self.assertEqual(exit_code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            self.assertIn("down.sql", payload["results"][0]["error"])


if __name__ == "__main__":
    unittest.main()
