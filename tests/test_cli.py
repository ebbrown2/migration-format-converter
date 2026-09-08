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


if __name__ == "__main__":
    unittest.main()
