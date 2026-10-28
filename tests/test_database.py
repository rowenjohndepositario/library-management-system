"""Run with: python -m unittest discover -s tests -v"""

import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import LibraryDatabase


class LibraryDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.now = date(2026, 1, 15)
        self.db = LibraryDatabase(self.path, today=lambda: self.now)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add_example(self, copies=1):
        book = self.db.add_book("The Hobbit", "J. R. R. Tolkien", "978-0547928227", copies)
        member = self.db.add_member("Alex Reader", "alex@example.com")
        return book, member

    def test_empty_library_and_validation(self):
        self.assertEqual(
            self.db.statistics(),
            {"titles": 0, "available": 0, "members": 0, "on_loan": 0, "overdue": 0},
        )
        for title, author, copies in [
            (" ", "Author", 1),
            ("Title", "", 1),
            ("Title", "Author", 0),
            ("Title", "Author", "1.5"),
        ]:
            with (
                self.subTest(title=title, author=author, copies=copies),
                self.assertRaises(ValueError),
            ):
                self.db.add_book(title, author, "", copies)
        with self.assertRaises(ValueError):
            self.db.add_member(" ")

        book, member = self.add_example()
        for due in ("", "2026-1-20", "2026-02-31", "2026-01-14"):
            with self.subTest(due=due), self.assertRaises(ValueError):
                self.db.issue_loan(book, member, due)
        self.assertEqual(len(self.db.list_loans(status="all")), 0)
        self.assertEqual(self.db.list_books()[0]["available"], 1)

    def test_checkout_return_and_overdue_filters(self):
        book, member = self.add_example(copies=2)
        loan = self.db.issue_loan(book, member, self.now.isoformat())
        self.assertEqual(self.db.list_books()[0]["available"], 1)
        self.assertEqual(
            self.db.statistics(),
            {"titles": 1, "available": 1, "members": 1, "on_loan": 1, "overdue": 0},
        )
        self.assertEqual(self.db.list_loans(status="active")[0]["status"], "On loan")
        self.assertEqual(self.db.list_loans(status="overdue"), [])

        self.now += timedelta(days=1)
        self.assertEqual(self.db.list_loans(status="overdue")[0]["status"], "Overdue")
        self.assertEqual(self.db.statistics()["overdue"], 1)
        self.db.return_loan(loan)
        self.assertEqual(self.db.list_loans(status="active"), [])
        returned = self.db.list_loans(status="returned")
        self.assertEqual(returned[0]["returned_on"], self.now.isoformat())
        self.assertEqual(returned[0]["status"], "Returned")
        self.assertEqual(self.db.list_books()[0]["available"], 2)
        with self.assertRaisesRegex(ValueError, "already been returned"):
            self.db.return_loan(loan)

    def test_prevents_overcheckout_and_preserves_history_when_archiving(self):
        book, member = self.add_example(copies=2)
        first = self.db.issue_loan(book, member, "2026-01-30")
        second = self.db.issue_loan(book, member, "2026-01-30")
        with self.assertRaisesRegex(ValueError, "No copies"):
            self.db.issue_loan(book, member, "2026-01-30")
        with self.assertRaisesRegex(ValueError, "currently on loan"):
            self.db.update_book(book, "The Hobbit", "Tolkien", "", 1)
        with self.assertRaisesRegex(ValueError, "Return all copies"):
            self.db.set_book_archived(book, True)
        with self.assertRaisesRegex(ValueError, "Return this member's loans"):
            self.db.set_member_archived(member, True)
        self.db.return_loan(first)
        self.db.update_book(book, "The Hobbit", "Tolkien", "", 1)
        self.assertEqual(self.db.list_books()[0]["available"], 0)
        self.db.return_loan(second)
        self.db.set_book_archived(book, True)
        self.db.set_member_archived(member, True)
        self.assertEqual(self.db.list_books(), [])
        self.assertEqual(self.db.list_members(), [])
        self.assertEqual(len(self.db.list_books(include_archived=True)), 1)
        self.assertEqual(len(self.db.list_members(include_archived=True)), 1)
        self.assertEqual(len(self.db.list_loans(status="all")), 2)
        with self.assertRaisesRegex(ValueError, "active book"):
            self.db.issue_loan(book, member, "2026-01-30")
        self.db.set_book_archived(book, False)
        self.db.set_member_archived(member, False)
        self.db.issue_loan(book, member, "2026-01-30")
        self.assertEqual(self.db.statistics()["available"], 0)

    def test_search_edits_and_persistence(self):
        book, member = self.add_example()
        self.db.add_book("Another Book", "Other Author", "", 1)
        self.assertEqual(len(self.db.list_books(search="TOLKIEN")), 1)
        self.assertEqual(len(self.db.list_books(search="978-054")), 1)
        self.assertEqual(len(self.db.list_members(search="example.com")), 1)
        self.assertEqual(self.db.list_books(search="%' OR 1=1 --"), [])
        self.db.update_book(book, "The Hobbit: Revised", "Tolkien", "123", 3)
        self.db.update_member(member, "Alex R.", "new contact")
        loan = self.db.issue_loan(book, member, "2026-01-20")
        self.assertEqual(len(self.db.list_loans(status="all", search="alex")), 1)

        other = LibraryDatabase(self.path, today=lambda: self.now)
        try:
            self.assertEqual(other.get_book(book)["title"], "The Hobbit: Revised")
            self.assertEqual(other.get_member(member)["contact"], "new contact")
            self.assertEqual(other.list_loans(status="all")[0]["id"], loan)
            self.assertEqual(other.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            other.close()

    def test_two_connections_cannot_issue_the_last_copy_twice(self):
        book, first_member = self.add_example()
        second_member = self.db.add_member("Second Member")
        barrier = threading.Barrier(2)

        def try_checkout(member):
            connection = LibraryDatabase(self.path, today=lambda: self.now)
            try:
                barrier.wait(timeout=10)
                try:
                    connection.issue_loan(book, member, "2026-01-30")
                    return "issued"
                except ValueError as error:
                    self.assertIn("No copies", str(error))
                    return "unavailable"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(try_checkout, (first_member, second_member)))
        self.assertCountEqual(results, ["issued", "unavailable"])
        self.assertEqual(len(self.db.list_loans(status="active")), 1)
        self.assertEqual(self.db.statistics()["available"], 0)


if __name__ == "__main__":
    unittest.main()
