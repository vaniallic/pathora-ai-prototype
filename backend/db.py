"""Database SQLite: tabel pengguna dan riwayat permintaan itinerary.

SQLite cukup untuk prototype dan demo. Kalau nanti pindah ke PostgreSQL, cukup ganti modul ini.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SKEMA = """
CREATE TABLE IF NOT EXISTS pengguna (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nama TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    dibuat TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS permintaan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pengguna_id INTEGER NOT NULL REFERENCES pengguna(id) ON DELETE CASCADE,
    teks TEXT NOT NULL,
    tipe TEXT NOT NULL,
    pesan TEXT NOT NULL,
    prefs TEXT,
    rencana TEXT,
    dibuat TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_permintaan_pengguna ON permintaan(pengguna_id, id DESC);
"""


def _sekarang():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path):
        self.path = str(path)
        with self.koneksi() as c:
            c.executescript(SKEMA)

    @contextmanager
    def koneksi(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---- pengguna ----
    def buat_pengguna(self, nama, email, password_hash):
        """Mengembalikan dict pengguna, atau None kalau email sudah terdaftar."""
        try:
            with self.koneksi() as c:
                cur = c.execute("INSERT INTO pengguna (nama, email, password_hash, dibuat) VALUES (?, ?, ?, ?)",
                                (nama, email, password_hash, _sekarang()))
                return self.pengguna_by_id(cur.lastrowid, c)
        except sqlite3.IntegrityError:
            return None

    def pengguna_by_email(self, email):
        with self.koneksi() as c:
            r = c.execute("SELECT * FROM pengguna WHERE email = ?", (email,)).fetchone()
            return dict(r) if r else None

    def pengguna_by_id(self, pid, c=None):
        if c is None:
            with self.koneksi() as c2:
                return self.pengguna_by_id(pid, c2)
        r = c.execute("SELECT * FROM pengguna WHERE id = ?", (pid,)).fetchone()
        return dict(r) if r else None

    # ---- riwayat permintaan ----
    def simpan_permintaan(self, pengguna_id, teks, hasil):
        with self.koneksi() as c:
            cur = c.execute(
                "INSERT INTO permintaan (pengguna_id, teks, tipe, pesan, prefs, rencana, dibuat) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pengguna_id, teks, hasil["tipe"], hasil["pesan"],
                 json.dumps(hasil.get("prefs"), ensure_ascii=False) if hasil.get("prefs") else None,
                 json.dumps(hasil.get("rencana"), ensure_ascii=False) if hasil.get("rencana") else None,
                 _sekarang()))
            return cur.lastrowid

    @staticmethod
    def _baris(r):
        d = dict(r)
        d["prefs"] = json.loads(d["prefs"]) if d["prefs"] else None
        d["rencana"] = json.loads(d["rencana"]) if d["rencana"] else None
        return d

    def daftar_permintaan(self, pengguna_id, batas=50):
        with self.koneksi() as c:
            rows = c.execute("SELECT * FROM permintaan WHERE pengguna_id = ? ORDER BY id DESC LIMIT ?",
                             (pengguna_id, batas)).fetchall()
            return [self._baris(r) for r in rows]

    def ambil_permintaan(self, pengguna_id, pid):
        with self.koneksi() as c:
            r = c.execute("SELECT * FROM permintaan WHERE id = ? AND pengguna_id = ?", (pid, pengguna_id)).fetchone()
            return self._baris(r) if r else None

    def hapus_permintaan(self, pengguna_id, pid):
        with self.koneksi() as c:
            return c.execute("DELETE FROM permintaan WHERE id = ? AND pengguna_id = ?", (pid, pengguna_id)).rowcount > 0
