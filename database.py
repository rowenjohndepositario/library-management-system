"""Database operations for the desktop library manager.

Only the Python standard library is required. The GUI calls this module for
all reads and writes, which makes the important rules easy to test separately.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path


class LibraryDatabase:
    """Store books, members and loans in a local SQLite database."""

    def __init__(
        self,
        path: str | Path,
        *,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.today = today
        if str(path) == ":memory:":
            database_path = ":memory:"
        else:
            resolved = Path(path).expanduser().resolve()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            database_path = str(resolved)

        self.connection = sqlite3.connect(database_path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_tables()

    def _create_tables(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL CHECK (length(trim(title)) > 0),
                author TEXT NOT NULL CHECK (length(trim(author)) > 0),
                isbn TEXT NOT NULL DEFAULT '',
                total_copies INTEGER NOT NULL CHECK (total_copies > 0),
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
            );

            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL CHECK (length(trim(name)) > 0),
                contact TEXT NOT NULL DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
            );

            CREATE TABLE IF NOT EXISTS loans (
                id INTEGER PRIMARY KEY,
                book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE RESTRICT,
                member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
                borrowed_on TEXT NOT NULL,
                due_on TEXT NOT NULL,
                returned_on TEXT,
                CHECK (due_on >= borrowed_on)
            );

            CREATE INDEX IF NOT EXISTS idx_loans_book_open
                ON loans(book_id, returned_on);
            CREATE INDEX IF NOT EXISTS idx_loans_member_open
                ON loans(member_id, returned_on);
            CREATE INDEX IF NOT EXISTS idx_loans_due
                ON loans(returned_on, due_on);
            """
        )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        # The write lock makes availability checks and checkout one operation,
        # even if two copies of the program access the same database.
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    @staticmethod
    def _required(value: object, label: str) -> str:
        text = str(value if value is not None else "").strip()
        if not text:
            raise ValueError(f"{label} is required.")
        return text

    @staticmethod
    def _optional(value: object) -> str:
        return str(value if value is not None else "").strip()

    @staticmethod
    def _copies(value: object) -> int:
        try:
            copies = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError("Copies must be a whole number between 1 and 1,000,000.") from None
        if not 1 <= copies <= 1_000_000:
            raise ValueError("Copies must be a whole number between 1 and 1,000,000.")
        return copies

    def close(self) -> None:
        self.connection.close()

    def add_book(self, title: str, author: str, isbn: str, copies: object) -> int:
        title = self._required(title, "Title")
        author = self._required(author, "Author")
        isbn = self._optional(isbn)
        count = self._copies(copies)
        with self._transaction():
            cursor = self.connection.execute(
                "INSERT INTO books (title, author, isbn, total_copies) VALUES (?, ?, ?, ?)",
                (title, author, isbn, count),
            )
            return int(cursor.lastrowid)

    def get_book(self, book_id: int) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()

    def update_book(self, book_id: int, title: str, author: str, isbn: str, copies: object) -> None:
        title = self._required(title, "Title")
        author = self._required(author, "Author")
        isbn = self._optional(isbn)
        count = self._copies(copies)
        with self._transaction():
            book = self.get_book(book_id)
            if book is None:
                raise ValueError("That book no longer exists.")
            if book["archived"]:
                raise ValueError("Restore this book before editing it.")
            borrowed = self.connection.execute(
                "SELECT COUNT(*) FROM loans WHERE book_id = ? AND returned_on IS NULL",
                (book_id,),
            ).fetchone()[0]
            if count < borrowed:
                raise ValueError(
                    f"Copies cannot be less than {borrowed}: that many are currently on loan."
                )
            self.connection.execute(
                "UPDATE books SET title = ?, author = ?, isbn = ?, total_copies = ? WHERE id = ?",
                (title, author, isbn, count, book_id),
            )

    def set_book_archived(self, book_id: int, archived: bool) -> None:
        with self._transaction():
            book = self.get_book(book_id)
            if book is None:
                raise ValueError("That book no longer exists.")
            if archived:
                outstanding = self.connection.execute(
                    "SELECT COUNT(*) FROM loans WHERE book_id = ? AND returned_on IS NULL",
                    (book_id,),
                ).fetchone()[0]
                if outstanding:
                    raise ValueError("Return all copies of this book before archiving it.")
            self.connection.execute(
                "UPDATE books SET archived = ? WHERE id = ?", (int(archived), book_id)
            )

    def list_books(
        self, *, search: str = "", include_archived: bool = False, available_only: bool = False
    ) -> list[sqlite3.Row]:
        term = search.strip()
        return self.connection.execute(
            """
            SELECT b.*, b.total_copies - COUNT(l.id) AS available
            FROM books AS b
            LEFT JOIN loans AS l ON l.book_id = b.id AND l.returned_on IS NULL
            WHERE (? = 1 OR b.archived = 0)
              AND (? = '' OR instr(lower(b.title), lower(?)) > 0
                          OR instr(lower(b.author), lower(?)) > 0
                          OR instr(lower(b.isbn), lower(?)) > 0)
            GROUP BY b.id
            HAVING (? = 0 OR available > 0)
            ORDER BY b.title COLLATE NOCASE, b.author COLLATE NOCASE, b.id
            """,
            (int(include_archived), term, term, term, term, int(available_only)),
        ).fetchall()

    def add_member(self, name: str, contact: str = "") -> int:
        name = self._required(name, "Member name")
        contact = self._optional(contact)
        with self._transaction():
            cursor = self.connection.execute(
                "INSERT INTO members (name, contact) VALUES (?, ?)", (name, contact)
            )
            return int(cursor.lastrowid)

    def get_member(self, member_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM members WHERE id = ?", (member_id,)
        ).fetchone()

    def update_member(self, member_id: int, name: str, contact: str = "") -> None:
        name = self._required(name, "Member name")
        contact = self._optional(contact)
        with self._transaction():
            member = self.get_member(member_id)
            if member is None:
                raise ValueError("That member no longer exists.")
            if member["archived"]:
                raise ValueError("Restore this member before editing them.")
            self.connection.execute(
                "UPDATE members SET name = ?, contact = ? WHERE id = ?",
                (name, contact, member_id),
            )

    def set_member_archived(self, member_id: int, archived: bool) -> None:
        with self._transaction():
            member = self.get_member(member_id)
            if member is None:
                raise ValueError("That member no longer exists.")
            if archived:
                outstanding = self.connection.execute(
                    "SELECT COUNT(*) FROM loans WHERE member_id = ? AND returned_on IS NULL",
                    (member_id,),
                ).fetchone()[0]
                if outstanding:
                    raise ValueError("Return this member's loans before archiving them.")
            self.connection.execute(
                "UPDATE members SET archived = ? WHERE id = ?", (int(archived), member_id)
            )

    def list_members(
        self, *, search: str = "", include_archived: bool = False
    ) -> list[sqlite3.Row]:
        term = search.strip()
        return self.connection.execute(
            """
            SELECT * FROM members
            WHERE (? = 1 OR archived = 0)
              AND (? = '' OR instr(lower(name), lower(?)) > 0
                          OR instr(lower(contact), lower(?)) > 0)
            ORDER BY name COLLATE NOCASE, id
            """,
            (int(include_archived), term, term, term),
        ).fetchall()

    def issue_loan(self, book_id: int, member_id: int, due_on: str) -> int:
        due_text = self._required(due_on, "Due date")
        try:
            due_date = date.fromisoformat(due_text)
        except ValueError:
            raise ValueError("Enter the due date as YYYY-MM-DD, for example 2026-12-31.") from None
        if due_date.isoformat() != due_text:
            raise ValueError("Enter the due date as YYYY-MM-DD, for example 2026-12-31.")
        today = self.today()
        if due_date < today:
            raise ValueError("The due date must be today or later.")

        with self._transaction():
            book = self.connection.execute(
                """
                SELECT b.total_copies,
                       (SELECT COUNT(*) FROM loans AS l
                        WHERE l.book_id = b.id AND l.returned_on IS NULL) AS borrowed
                FROM books AS b WHERE b.id = ? AND b.archived = 0
                """,
                (book_id,),
            ).fetchone()
            if book is None:
                raise ValueError("Choose an active book.")
            if book["borrowed"] >= book["total_copies"]:
                raise ValueError("No copies of this book are available.")
            member = self.connection.execute(
                "SELECT id FROM members WHERE id = ? AND archived = 0", (member_id,)
            ).fetchone()
            if member is None:
                raise ValueError("Choose an active member.")
            cursor = self.connection.execute(
                "INSERT INTO loans (book_id, member_id, borrowed_on, due_on) VALUES (?, ?, ?, ?)",
                (book_id, member_id, today.isoformat(), due_date.isoformat()),
            )
            return int(cursor.lastrowid)

    def return_loan(self, loan_id: int) -> None:
        with self._transaction():
            loan = self.connection.execute(
                "SELECT returned_on FROM loans WHERE id = ?", (loan_id,)
            ).fetchone()
            if loan is None:
                raise ValueError("That loan no longer exists.")
            if loan["returned_on"] is not None:
                raise ValueError("This loan has already been returned.")
            self.connection.execute(
                "UPDATE loans SET returned_on = ? WHERE id = ?",
                (self.today().isoformat(), loan_id),
            )

    def list_loans(self, *, status: str = "active", search: str = "") -> list[sqlite3.Row]:
        if status not in {"active", "overdue", "returned", "all"}:
            raise ValueError("Unknown loan filter.")
        term = search.strip()
        today = self.today().isoformat()
        where = [
            "(? = '' OR instr(lower(b.title), lower(?)) > 0 OR instr(lower(m.name), lower(?)) > 0)"
        ]
        params: list[object] = [today, term, term, term]
        if status == "active":
            where.append("l.returned_on IS NULL")
        elif status == "overdue":
            where.append("l.returned_on IS NULL AND l.due_on < ?")
            params.append(today)
        elif status == "returned":
            where.append("l.returned_on IS NOT NULL")
        sql = f"""
            SELECT l.*, b.title AS book_title, m.name AS member_name,
                   CASE WHEN l.returned_on IS NOT NULL THEN 'Returned'
                        WHEN l.due_on < ? THEN 'Overdue'
                        ELSE 'On loan' END AS status
            FROM loans AS l
            JOIN books AS b ON b.id = l.book_id
            JOIN members AS m ON m.id = l.member_id
            WHERE {" AND ".join(where)}
            ORDER BY CASE WHEN l.returned_on IS NULL THEN 0 ELSE 1 END,
                     l.due_on, l.id DESC
        """
        return self.connection.execute(sql, params).fetchall()

    def statistics(self) -> dict[str, int]:
        books = self.connection.execute(
            "SELECT COUNT(*) AS titles, COALESCE(SUM(total_copies), 0) AS copies "
            "FROM books WHERE archived = 0"
        ).fetchone()
        members = self.connection.execute(
            "SELECT COUNT(*) FROM members WHERE archived = 0"
        ).fetchone()[0]
        loans = self.connection.execute(
            """
            SELECT COUNT(*) AS active,
                   COALESCE(SUM(CASE WHEN due_on < ? THEN 1 ELSE 0 END), 0) AS overdue
            FROM loans WHERE returned_on IS NULL
            """,
            (self.today().isoformat(),),
        ).fetchone()
        return {
            "titles": books["titles"],
            "available": books["copies"] - loans["active"],
            "members": members,
            "on_loan": loans["active"],
            "overdue": loans["overdue"],
        }
