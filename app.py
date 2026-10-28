"""Shelf: a small, local desktop library management system."""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tkinter as tk
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

from database import LibraryDatabase

BACKGROUND = "#f2f5fa"
WHITE = "#ffffff"
INK = "#1b2942"
MUTED = "#6e7b90"
BORDER = "#dce4ef"
BLUE = "#315fd4"
DARK_BLUE = "#244db6"
DEFAULT_DATABASE = Path(__file__).resolve().parent / "data" / "library.sqlite3"
FONT = "Segoe UI"


def center_dialog(dialog: tk.Toplevel, parent: tk.Misc) -> None:
    dialog.update_idletasks()
    width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
    x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
    dialog.geometry(f"+{max(0, x)}+{max(0, y)}")


def show_error(parent: tk.Misc, error: Exception) -> None:
    if isinstance(error, ValueError):
        messagebox.showwarning("Check your details", str(error), parent=parent)
    else:
        messagebox.showerror(
            "Database error", f"The operation could not be completed.\n\n{error}", parent=parent
        )


class FormDialog(tk.Toplevel):
    """Simple modal form for adding or editing a book or member."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        fields: list[tuple[str, str, str]],
        save: Callable[[dict[str, str]], None],
        on_success: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.configure(background=WHITE)
        self.save_callback = save
        self.on_success = on_success
        self.variables: dict[str, tk.StringVar] = {}

        content = tk.Frame(self, background=WHITE, padx=25, pady=22)
        content.pack(fill="both", expand=True)
        tk.Label(content, text=title, bg=WHITE, fg=INK, font=(FONT, 17, "bold"), anchor="w").pack(
            fill="x", pady=(0, 16)
        )
        first_entry = None
        for key, label, value in fields:
            tk.Label(
                content, text=label, bg=WHITE, fg=INK, font=(FONT, 10, "bold"), anchor="w"
            ).pack(fill="x", pady=(7, 4))
            variable = tk.StringVar(master=self, value=str(value))
            self.variables[key] = variable
            entry = ttk.Entry(content, textvariable=variable, width=47)
            entry.pack(fill="x", ipady=4)
            if first_entry is None:
                first_entry = entry

        actions = tk.Frame(content, bg=WHITE)
        actions.pack(fill="x", pady=(22, 0))
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(actions, text="Save", style="Primary.TButton", command=self._save).pack(
            side="right"
        )
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", self._save)
        center_dialog(self, parent)
        self.grab_set()
        if first_entry is not None:
            first_entry.focus_set()

    def _save(self, _event: tk.Event | None = None) -> None:
        try:
            self.save_callback({key: variable.get() for key, variable in self.variables.items()})
        except (ValueError, sqlite3.Error, OSError) as error:
            show_error(self, error)
            return
        self.destroy()
        self.on_success()


class LoanDialog(tk.Toplevel):
    """Choose an available book, a member and the due date."""

    def __init__(
        self, parent: tk.Misc, database: LibraryDatabase, on_success: Callable[[], None]
    ) -> None:
        super().__init__(parent)
        self.title("Issue a book")
        self.transient(parent)
        self.resizable(False, False)
        self.configure(background=WHITE)
        self.database = database
        self.on_success = on_success

        books = database.list_books(available_only=True)
        members = database.list_members()
        self.books = {
            f"{book['title']} — {book['author']}  (#{book['id']}, {book['available']} available)": book[
                "id"
            ]
            for book in books
        }
        self.members = {f"{member['name']}  (#{member['id']})": member["id"] for member in members}
        self.book_var = tk.StringVar(master=self)
        self.member_var = tk.StringVar(master=self)
        self.due_var = tk.StringVar(
            master=self, value=(date.today() + timedelta(days=14)).isoformat()
        )

        content = tk.Frame(self, bg=WHITE, padx=25, pady=22)
        content.pack(fill="both", expand=True)
        tk.Label(content, text="Issue a book", bg=WHITE, fg=INK, font=(FONT, 17, "bold")).pack(
            anchor="w", pady=(0, 4)
        )
        tk.Label(
            content,
            text="Select a book and member, then set the return date.",
            bg=WHITE,
            fg=MUTED,
            font=(FONT, 10),
        ).pack(anchor="w", pady=(0, 12))

        tk.Label(content, text="Available book", bg=WHITE, fg=INK, font=(FONT, 10, "bold")).pack(
            anchor="w", pady=(7, 4)
        )
        book_box = ttk.Combobox(
            content, values=list(self.books), textvariable=self.book_var, state="readonly", width=54
        )
        book_box.pack(fill="x", ipady=4)
        if books:
            book_box.current(0)

        tk.Label(content, text="Member", bg=WHITE, fg=INK, font=(FONT, 10, "bold")).pack(
            anchor="w", pady=(12, 4)
        )
        member_box = ttk.Combobox(
            content,
            values=list(self.members),
            textvariable=self.member_var,
            state="readonly",
            width=54,
        )
        member_box.pack(fill="x", ipady=4)
        if members:
            member_box.current(0)

        tk.Label(
            content, text="Due date  ·  YYYY-MM-DD", bg=WHITE, fg=INK, font=(FONT, 10, "bold")
        ).pack(anchor="w", pady=(12, 4))
        ttk.Entry(content, textvariable=self.due_var).pack(fill="x", ipady=4)
        tk.Label(
            content, text="The default loan period is 14 days.", bg=WHITE, fg=MUTED, font=(FONT, 9)
        ).pack(anchor="w", pady=(5, 0))

        actions = tk.Frame(content, bg=WHITE)
        actions.pack(fill="x", pady=(22, 0))
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(actions, text="Issue book", style="Primary.TButton", command=self._save).pack(
            side="right"
        )
        self.bind("<Escape>", lambda _event: self.destroy())
        center_dialog(self, parent)
        self.grab_set()
        book_box.focus_set()

    def _save(self) -> None:
        try:
            book_id = self.books.get(self.book_var.get())
            member_id = self.members.get(self.member_var.get())
            if book_id is None or member_id is None:
                raise ValueError("Choose an available book and a member.")
            self.database.issue_loan(book_id, member_id, self.due_var.get())
        except (ValueError, sqlite3.Error, OSError) as error:
            show_error(self, error)
            return
        self.destroy()
        self.on_success()


class LibraryApp:
    def __init__(self, root: tk.Tk, database: LibraryDatabase) -> None:
        self.root = root
        self.database = database
        root.title("Shelf | Library Manager")
        root.geometry("1200x760")
        root.minsize(900, 620)
        root.configure(bg=BACKGROUND)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_styles()

        self.book_search = tk.StringVar(master=root)
        self.member_search = tk.StringVar(master=root)
        self.loan_search = tk.StringVar(master=root)
        self.show_archived_books = tk.BooleanVar(master=root, value=False)
        self.show_archived_members = tk.BooleanVar(master=root, value=False)
        self.loan_filter = tk.StringVar(master=root, value="Active")
        initial_counts = database.statistics()
        if not initial_counts["titles"]:
            welcome = "Add a book to get started."
        elif not initial_counts["members"]:
            welcome = "Add a member before issuing a loan."
        else:
            welcome = "Ready. Your library data is saved on this computer."
        self.status_message = tk.StringVar(master=root, value=welcome)
        self.stat_values = {
            key: tk.StringVar(master=root, value="0")
            for key in ("titles", "available", "members", "on_loan", "overdue")
        }

        shell = tk.Frame(root, bg=BACKGROUND)
        shell.pack(fill="both", expand=True, padx=26, pady=(20, 13))
        self._build_header(shell)
        self._build_statistics(shell)

        # Reserve space for the status bar before giving the notebook the rest.
        status_bar = tk.Frame(shell, bg=BACKGROUND)
        status_bar.pack(side="bottom", fill="x", pady=(10, 0))
        tk.Label(
            status_bar, textvariable=self.status_message, bg=BACKGROUND, fg=MUTED, font=(FONT, 9)
        ).pack(side="left")
        tk.Label(
            status_bar,
            text="SHELF  /  LOCAL EDITION",
            bg=BACKGROUND,
            fg="#97a4b6",
            font=(FONT, 8, "bold"),
        ).pack(side="right")

        self.tabs = ttk.Notebook(shell)
        self.tabs.pack(fill="both", expand=True, pady=(4, 0))
        books_page = tk.Frame(self.tabs, bg=WHITE)
        members_page = tk.Frame(self.tabs, bg=WHITE)
        loans_page = tk.Frame(self.tabs, bg=WHITE)
        self.tabs.add(books_page, text="  Books  ")
        self.tabs.add(members_page, text="  Members  ")
        self.tabs.add(loans_page, text="  Loans  ")
        self._build_books(books_page)
        self._build_members(members_page)
        self._build_loans(loans_page)

        self.book_search.trace_add("write", lambda *_: self.refresh_books())
        self.member_search.trace_add("write", lambda *_: self.refresh_members())
        self.loan_search.trace_add("write", lambda *_: self.refresh_loans())
        self.refresh_all()
        root.after(60_000, self._periodic_refresh)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(
            "TButton",
            font=(FONT, 10, "bold"),
            padding=(13, 8),
            background="#eef2f8",
            foreground=INK,
            borderwidth=0,
        )
        style.map("TButton", background=[("active", "#e1e8f2"), ("disabled", "#f3f5f8")])
        style.configure("Primary.TButton", background=BLUE, foreground=WHITE)
        style.map(
            "Primary.TButton",
            background=[("active", DARK_BLUE), ("disabled", "#9eadd2")],
            foreground=[("disabled", "#f1f1f1")],
        )
        style.configure("Page.TCheckbutton", background=WHITE, foreground=INK, font=(FONT, 9))
        style.map("Page.TCheckbutton", background=[("active", WHITE)])
        style.configure("TNotebook", background=BACKGROUND, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#e7edf6",
            foreground=MUTED,
            padding=(17, 10),
            font=(FONT, 10, "bold"),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", WHITE), ("active", "#eef2f8")],
            foreground=[("selected", INK)],
        )
        style.configure(
            "Library.Treeview",
            background=WHITE,
            fieldbackground=WHITE,
            foreground=INK,
            rowheight=35,
            borderwidth=0,
            font=(FONT, 10),
        )
        style.configure(
            "Library.Treeview.Heading",
            background="#f2f5fa",
            foreground="#66758a",
            relief="flat",
            font=(FONT, 9, "bold"),
            padding=(8, 9),
        )
        style.map(
            "Library.Treeview", background=[("selected", "#e1eafd")], foreground=[("selected", INK)]
        )
        style.map("Library.Treeview.Heading", background=[("active", "#e8eef7")])
        style.configure("TEntry", padding=5)
        style.configure("TCombobox", padding=4)

    def _build_header(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=BACKGROUND)
        header.pack(fill="x", pady=(0, 20))
        left = tk.Frame(header, bg=BACKGROUND)
        left.pack(side="left")
        tk.Label(
            left, text="SHELF  /  LIBRARY MANAGER", bg=BACKGROUND, fg=BLUE, font=(FONT, 9, "bold")
        ).pack(anchor="w")
        tk.Label(
            left, text="Your library, organized.", bg=BACKGROUND, fg=INK, font=(FONT, 23, "bold")
        ).pack(anchor="w", pady=(2, 1))
        tk.Label(
            left,
            text="Books, members and borrowing — all in one place.",
            bg=BACKGROUND,
            fg=MUTED,
            font=(FONT, 10),
        ).pack(anchor="w")
        badge = tk.Frame(header, bg="#e6f2ed", padx=11, pady=6)
        badge.pack(side="right", anchor="n", pady=6)
        tk.Label(
            badge,
            text="●  SAVED ON THIS COMPUTER",
            bg="#e6f2ed",
            fg="#2d8066",
            font=(FONT, 8, "bold"),
        ).pack()

    def _build_statistics(self, parent: tk.Frame) -> None:
        section = tk.Frame(parent, bg=BACKGROUND)
        section.pack(fill="x", pady=(0, 17))
        labels = [
            ("titles", "BOOK TITLES"),
            ("available", "COPIES AVAILABLE"),
            ("members", "MEMBERS"),
            ("on_loan", "ON LOAN"),
            ("overdue", "OVERDUE"),
        ]
        for index, (key, label) in enumerate(labels):
            section.columnconfigure(index, weight=1, uniform="cards")
            card = tk.Frame(
                section,
                bg=WHITE,
                highlightbackground=BORDER,
                highlightthickness=1,
                padx=16,
                pady=10,
            )
            card.grid(
                row=0, column=index, sticky="nsew", padx=(0, 9 if index < len(labels) - 1 else 0)
            )
            tk.Label(card, text=label, bg=WHITE, fg=MUTED, font=(FONT, 8, "bold")).pack(anchor="w")
            tk.Label(
                card,
                textvariable=self.stat_values[key],
                bg=WHITE,
                fg="#c55050" if key == "overdue" else INK,
                font=(FONT, 21, "bold"),
            ).pack(anchor="w", pady=(3, 0))

    @staticmethod
    def _page_header(page: tk.Frame, title: str, subtitle: str) -> tuple[tk.Frame, tk.Frame]:
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        header = tk.Frame(page, bg=WHITE)
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 12))
        labels = tk.Frame(header, bg=WHITE)
        labels.pack(side="left")
        tk.Label(labels, text=title, bg=WHITE, fg=INK, font=(FONT, 16, "bold")).pack(anchor="w")
        tk.Label(labels, text=subtitle, bg=WHITE, fg=MUTED, font=(FONT, 9)).pack(
            anchor="w", pady=(2, 0)
        )
        actions = tk.Frame(header, bg=WHITE)
        actions.pack(side="right")
        toolbar = tk.Frame(page, bg=WHITE)
        toolbar.grid(row=1, column=0, sticky="ew", padx=20, pady=(2, 12))
        return actions, toolbar

    @staticmethod
    def _table(page: tk.Frame, columns: list[tuple[str, str, int, str]]) -> ttk.Treeview:
        container = tk.Frame(page, bg=WHITE)
        container.grid(row=2, column=0, sticky="nsew", padx=20)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        tree = ttk.Treeview(
            container,
            columns=[column[0] for column in columns],
            show="headings",
            selectmode="browse",
            style="Library.Treeview",
        )
        content_minimum = {
            "title": 150,
            "author": 130,
            "isbn": 140,
            "book": 160,
            "member": 130,
            "borrowed": 100,
            "due": 100,
            "returned": 100,
        }
        for key, heading, width, anchor in columns:
            tree.heading(key, text=heading, anchor=anchor)
            # Keep headings and common identifiers legible on smaller windows.
            minimum = min(width, max(65, len(heading) * 9 + 20, content_minimum.get(key, 0)))
            tree.column(key, width=width, minwidth=minimum, anchor=anchor, stretch=True)
        vertical = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(container, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.tag_configure("archived", foreground="#98a4b4")
        tree.tag_configure("overdue", foreground="#b73c3c", background="#fff2f1")
        tree.tag_configure("returned", foreground="#8a98aa")
        return tree

    def _build_books(self, page: tk.Frame) -> None:
        actions, toolbar = self._page_header(
            page, "Books", "Manage the titles and copies in your collection."
        )
        ttk.Button(actions, text="+ Add book", style="Primary.TButton", command=self.add_book).pack(
            side="left", padx=(0, 7)
        )
        ttk.Button(actions, text="Edit", command=self.edit_book).pack(side="left", padx=(0, 7))
        ttk.Button(actions, text="Archive / restore", command=self.archive_book).pack(side="left")
        tk.Label(toolbar, text="SEARCH", bg=WHITE, fg=MUTED, font=(FONT, 8, "bold")).pack(
            side="left", padx=(0, 8)
        )
        ttk.Entry(toolbar, textvariable=self.book_search, width=32).pack(side="left")
        tk.Label(toolbar, text="Title, author or ISBN", bg=WHITE, fg=MUTED, font=(FONT, 9)).pack(
            side="left", padx=10
        )
        ttk.Checkbutton(
            toolbar,
            text="Show archived",
            style="Page.TCheckbutton",
            variable=self.show_archived_books,
            command=self.refresh_books,
        ).pack(side="right")
        self.books_tree = self._table(
            page,
            [
                ("id", "ID", 65, "center"),
                ("title", "TITLE", 260, "w"),
                ("author", "AUTHOR", 185, "w"),
                ("isbn", "ISBN", 155, "w"),
                ("copies", "COPIES", 90, "center"),
                ("available", "AVAILABLE", 105, "center"),
                ("status", "STATUS", 100, "center"),
            ],
        )
        self.books_tree.bind("<Double-1>", lambda _event: self.edit_book())
        self.books_note = tk.StringVar(master=self.root)
        tk.Label(
            page, textvariable=self.books_note, bg=WHITE, fg=MUTED, font=(FONT, 9), anchor="w"
        ).grid(row=3, column=0, sticky="ew", padx=21, pady=(9, 15))

    def _build_members(self, page: tk.Frame) -> None:
        actions, toolbar = self._page_header(
            page, "Members", "Keep track of the people who borrow books."
        )
        ttk.Button(
            actions, text="+ Add member", style="Primary.TButton", command=self.add_member
        ).pack(side="left", padx=(0, 7))
        ttk.Button(actions, text="Edit", command=self.edit_member).pack(side="left", padx=(0, 7))
        ttk.Button(actions, text="Archive / restore", command=self.archive_member).pack(side="left")
        tk.Label(toolbar, text="SEARCH", bg=WHITE, fg=MUTED, font=(FONT, 8, "bold")).pack(
            side="left", padx=(0, 8)
        )
        ttk.Entry(toolbar, textvariable=self.member_search, width=32).pack(side="left")
        tk.Label(toolbar, text="Name or contact", bg=WHITE, fg=MUTED, font=(FONT, 9)).pack(
            side="left", padx=10
        )
        ttk.Checkbutton(
            toolbar,
            text="Show archived",
            style="Page.TCheckbutton",
            variable=self.show_archived_members,
            command=self.refresh_members,
        ).pack(side="right")
        self.members_tree = self._table(
            page,
            [
                ("id", "ID", 75, "center"),
                ("name", "MEMBER NAME", 320, "w"),
                ("contact", "CONTACT", 360, "w"),
                ("status", "STATUS", 130, "center"),
            ],
        )
        self.members_tree.bind("<Double-1>", lambda _event: self.edit_member())
        self.members_note = tk.StringVar(master=self.root)
        tk.Label(
            page, textvariable=self.members_note, bg=WHITE, fg=MUTED, font=(FONT, 9), anchor="w"
        ).grid(row=3, column=0, sticky="ew", padx=21, pady=(9, 15))

    def _build_loans(self, page: tk.Frame) -> None:
        actions, toolbar = self._page_header(
            page, "Loans", "Issue books, record returns and spot overdue loans."
        )
        ttk.Button(
            actions, text="+ Issue book", style="Primary.TButton", command=self.issue_book
        ).pack(side="left", padx=(0, 7))
        ttk.Button(actions, text="Mark returned", command=self.return_book).pack(side="left")
        tk.Label(toolbar, text="SEARCH", bg=WHITE, fg=MUTED, font=(FONT, 8, "bold")).pack(
            side="left", padx=(0, 8)
        )
        ttk.Entry(toolbar, textvariable=self.loan_search, width=27).pack(side="left")
        tk.Label(toolbar, text="Book or member", bg=WHITE, fg=MUTED, font=(FONT, 9)).pack(
            side="left", padx=10
        )
        filter_box = ttk.Combobox(
            toolbar,
            textvariable=self.loan_filter,
            state="readonly",
            width=12,
            values=("Active", "Overdue", "Returned", "All"),
        )
        filter_box.pack(side="right")
        tk.Label(toolbar, text="SHOW", bg=WHITE, fg=MUTED, font=(FONT, 8, "bold")).pack(
            side="right", padx=(10, 6)
        )
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_loans())
        self.loans_tree = self._table(
            page,
            [
                ("id", "ID", 60, "center"),
                ("book", "BOOK", 235, "w"),
                ("member", "MEMBER", 175, "w"),
                ("borrowed", "ISSUED", 110, "center"),
                ("due", "DUE", 110, "center"),
                ("status", "STATUS", 100, "center"),
                ("returned", "RETURNED", 110, "center"),
            ],
        )
        self.loans_note = tk.StringVar(master=self.root)
        tk.Label(
            page, textvariable=self.loans_note, bg=WHITE, fg=MUTED, font=(FONT, 9), anchor="w"
        ).grid(row=3, column=0, sticky="ew", padx=21, pady=(9, 15))

    @staticmethod
    def _replace_rows(tree: ttk.Treeview, rows: list[tuple[str, tuple[object, ...], str]]) -> None:
        selected = tree.selection()
        tree.delete(*tree.get_children())
        for row_id, values, tag in rows:
            tree.insert("", "end", iid=row_id, values=values, tags=(tag,) if tag else ())
        if selected and tree.exists(selected[0]):
            tree.selection_set(selected[0])
            tree.focus(selected[0])

    def refresh_books(self) -> None:
        books = self.database.list_books(
            search=self.book_search.get(), include_archived=self.show_archived_books.get()
        )
        self._replace_rows(
            self.books_tree,
            [
                (
                    str(book["id"]),
                    (
                        book["id"],
                        book["title"],
                        book["author"],
                        book["isbn"] or "—",
                        book["total_copies"],
                        book["available"],
                        "Archived" if book["archived"] else "Active",
                    ),
                    "archived" if book["archived"] else "",
                )
                for book in books
            ],
        )
        self.books_note.set(
            f"{len(books)} shown  ·  Archive records to keep their loan history; restore them any time."
        )

    def refresh_members(self) -> None:
        members = self.database.list_members(
            search=self.member_search.get(), include_archived=self.show_archived_members.get()
        )
        self._replace_rows(
            self.members_tree,
            [
                (
                    str(member["id"]),
                    (
                        member["id"],
                        member["name"],
                        member["contact"] or "—",
                        "Archived" if member["archived"] else "Active",
                    ),
                    "archived" if member["archived"] else "",
                )
                for member in members
            ],
        )
        self.members_note.set(
            f"{len(members)} shown  ·  Members with active loans must return them before being archived."
        )

    def refresh_loans(self) -> None:
        loans = self.database.list_loans(
            status=self.loan_filter.get().lower(), search=self.loan_search.get()
        )
        self._replace_rows(
            self.loans_tree,
            [
                (
                    str(loan["id"]),
                    (
                        loan["id"],
                        loan["book_title"],
                        loan["member_name"],
                        loan["borrowed_on"],
                        loan["due_on"],
                        loan["status"],
                        loan["returned_on"] or "—",
                    ),
                    "overdue"
                    if loan["status"] == "Overdue"
                    else "returned"
                    if loan["status"] == "Returned"
                    else "",
                )
                for loan in loans
            ],
        )
        self.loans_note.set(
            f"{len(loans)} shown  ·  A loan becomes overdue the day after its due date."
        )

    def refresh_all(self) -> None:
        self.refresh_books()
        self.refresh_members()
        self.refresh_loans()
        for key, value in self.database.statistics().items():
            self.stat_values[key].set(str(value))

    def _periodic_refresh(self) -> None:
        try:
            self.refresh_all()
        except sqlite3.Error:
            self.status_message.set("Could not refresh the database. Try again or restart the app.")
        self.root.after(60_000, self._periodic_refresh)

    def _selected_id(self, tree: ttk.Treeview, label: str) -> int | None:
        selected = tree.selection()
        if not selected:
            messagebox.showinfo("Select a record", f"Select a {label} first.", parent=self.root)
            return None
        return int(selected[0])

    def _completed(self, message: str) -> None:
        self.refresh_all()
        self.status_message.set(message)

    def _perform(self, operation: Callable[[], None], message: str) -> None:
        try:
            operation()
        except (ValueError, sqlite3.Error, OSError) as error:
            show_error(self.root, error)
            return
        self._completed(message)

    def add_book(self) -> None:
        self._book_dialog(None)

    def edit_book(self) -> None:
        book_id = self._selected_id(self.books_tree, "book")
        if book_id is None:
            return
        book = self.database.get_book(book_id)
        if book is None:
            messagebox.showwarning(
                "Book not found", "This book no longer exists.", parent=self.root
            )
        elif book["archived"]:
            messagebox.showinfo(
                "Archived book", "Restore this book before editing it.", parent=self.root
            )
        else:
            self._book_dialog(book)

    def _book_dialog(self, book: sqlite3.Row | None) -> None:
        fields = [
            ("title", "Title *", book["title"] if book else ""),
            ("author", "Author *", book["author"] if book else ""),
            ("isbn", "ISBN (optional)", book["isbn"] if book else ""),
            ("copies", "Number of copies *", str(book["total_copies"]) if book else "1"),
        ]

        def save(values: dict[str, str]) -> None:
            arguments = (values["title"], values["author"], values["isbn"], values["copies"])
            if book:
                self.database.update_book(book["id"], *arguments)
            else:
                self.database.add_book(*arguments)

        FormDialog(
            self.root,
            "Edit book" if book else "Add a book",
            fields,
            save,
            lambda: self._completed("Book saved."),
        )

    def archive_book(self) -> None:
        book_id = self._selected_id(self.books_tree, "book")
        if book_id is None:
            return
        book = self.database.get_book(book_id)
        if book is None:
            messagebox.showwarning(
                "Book not found", "This book no longer exists.", parent=self.root
            )
            self.refresh_all()
            return
        restore = bool(book["archived"])
        action = "Restore" if restore else "Archive"
        detail = (
            "It will appear in the active collection again."
            if restore
            else "Its history will be kept, and it can be restored later."
        )
        if messagebox.askyesno(
            f"{action} book?", f"{action} ‘{book['title']}’?\n\n{detail}", parent=self.root
        ):
            self._perform(
                lambda: self.database.set_book_archived(book_id, not restore),
                f"Book {'restored' if restore else 'archived'}.",
            )

    def add_member(self) -> None:
        self._member_dialog(None)

    def edit_member(self) -> None:
        member_id = self._selected_id(self.members_tree, "member")
        if member_id is None:
            return
        member = self.database.get_member(member_id)
        if member is None:
            messagebox.showwarning(
                "Member not found", "This member no longer exists.", parent=self.root
            )
        elif member["archived"]:
            messagebox.showinfo(
                "Archived member", "Restore this member before editing them.", parent=self.root
            )
        else:
            self._member_dialog(member)

    def _member_dialog(self, member: sqlite3.Row | None) -> None:
        fields = [
            ("name", "Member name *", member["name"] if member else ""),
            ("contact", "Email or phone (optional)", member["contact"] if member else ""),
        ]

        def save(values: dict[str, str]) -> None:
            if member:
                self.database.update_member(member["id"], values["name"], values["contact"])
            else:
                self.database.add_member(values["name"], values["contact"])

        FormDialog(
            self.root,
            "Edit member" if member else "Add a member",
            fields,
            save,
            lambda: self._completed("Member saved."),
        )

    def archive_member(self) -> None:
        member_id = self._selected_id(self.members_tree, "member")
        if member_id is None:
            return
        member = self.database.get_member(member_id)
        if member is None:
            messagebox.showwarning(
                "Member not found", "This member no longer exists.", parent=self.root
            )
            self.refresh_all()
            return
        restore = bool(member["archived"])
        action = "Restore" if restore else "Archive"
        detail = (
            "They will appear in the active members list again."
            if restore
            else "Their loan history will be kept, and they can be restored later."
        )
        if messagebox.askyesno(
            f"{action} member?", f"{action} ‘{member['name']}’?\n\n{detail}", parent=self.root
        ):
            self._perform(
                lambda: self.database.set_member_archived(member_id, not restore),
                f"Member {'restored' if restore else 'archived'}.",
            )

    def issue_book(self) -> None:
        if not self.database.list_books(available_only=True):
            messagebox.showinfo(
                "No available books",
                "Add a book with an available copy before issuing a loan.",
                parent=self.root,
            )
            return
        if not self.database.list_members():
            messagebox.showinfo(
                "No members", "Add a member before issuing a loan.", parent=self.root
            )
            return
        LoanDialog(self.root, self.database, lambda: self._completed("Book issued."))

    def return_book(self) -> None:
        loan_id = self._selected_id(self.loans_tree, "loan")
        if loan_id is None:
            return
        if messagebox.askyesno(
            "Mark returned?", "Mark the selected loan as returned?", parent=self.root
        ):
            self._perform(lambda: self.database.return_loan(loan_id), "Book returned.")

    def close(self) -> None:
        self.database.close()
        self.root.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="A local desktop library management system.")
    parser.add_argument(
        "--database", type=Path, default=DEFAULT_DATABASE, help="Path to the SQLite database file."
    )
    args = parser.parse_args()
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(
            f"Could not open the desktop window. Run this app on a computer with a graphical display.\n{error}",
            file=sys.stderr,
        )
        return 1
    try:
        database = LibraryDatabase(args.database)
    except (sqlite3.Error, OSError) as error:
        messagebox.showerror("Could not open the database", str(error), parent=root)
        root.destroy()
        return 1
    LibraryApp(root, database)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
