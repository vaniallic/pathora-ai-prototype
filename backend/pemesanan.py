"""P2: pemesanan. Trip, anggota, item kegiatan, pengajuan ke host, keputusan host, patungan, pembayaran
simulasi, payout host, Paspor Alam, dan paket Plus.

Aturan bisnis mengikuti BACKEND-BRIEF bagian 6.3 dan store.js di front-end:
- status item: draft -> diajukan -> disetujui | ditolak; disetujui -> lunas (setelah dibayar)
- pembayaran hanya untuk item disetujui; item ditolak tidak dikenai biaya
- keputusan hanya oleh host pemilik kegiatan
- kuota: jumlah orang yang disetujui/lunas di satu sesi (kegiatan + tanggal + jam) tidak boleh melebihi kuota
- hari tutup: kegiatan tidak bisa diajukan pada tanggal yang ditutup host, dan kegiatan yang terpengaruh purnama
  atau tilem dianggap tutup pada hari itu (tanggal dihitung astronomis, lihat kalender.py)
- duplikat: kegiatan yang sama di tanggal yang sama (selain ditolak) tidak boleh dua kali dalam satu trip
- biaya item = harga per orang x jumlah orang (angka dari data, bukan dari pengguna)
- patungan: saldo (dibayar - bagian), pelunasan greedy dari yang paling berutang (sama dengan PS.settle())
- stempel paspor: setelah item lunas dan host memberi kode hadir; satu stempel per kegiatan per pengguna

Semua pembayaran di sini SIMULASI. Tidak ada uang yang berpindah.
"""
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from .kalender import fase_bulan, fase_pada

STATUS_ITEM = ("draft", "diajukan", "disetujui", "ditolak", "lunas")
POLA_JAM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
WIB = timezone(timedelta(hours=7))

SKEMA = """
CREATE TABLE IF NOT EXISTS trip (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nama TEXT NOT NULL,
    tanggal_mulai TEXT NOT NULL,
    tanggal_akhir TEXT NOT NULL,
    bendahara_id INTEGER NOT NULL REFERENCES pengguna(id),
    kode TEXT NOT NULL UNIQUE,
    dibuat TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS anggota (
    trip_id INTEGER NOT NULL REFERENCES trip(id) ON DELETE CASCADE,
    pengguna_id INTEGER NOT NULL REFERENCES pengguna(id) ON DELETE CASCADE,
    hari_sibuk TEXT NOT NULL DEFAULT '[]',
    bergabung TEXT NOT NULL,
    PRIMARY KEY (trip_id, pengguna_id)
);
CREATE TABLE IF NOT EXISTS item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL REFERENCES trip(id) ON DELETE CASCADE,
    kegiatan_id TEXT NOT NULL,
    tanggal TEXT NOT NULL,
    jam TEXT NOT NULL,
    jumlah_orang INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    oleh_id INTEGER NOT NULL REFERENCES pengguna(id),
    kode_hadir TEXT,
    dibuat TEXT NOT NULL,
    diperbarui TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_item_sesi ON item(kegiatan_id, tanggal, jam, status);
CREATE TABLE IF NOT EXISTS acara (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL REFERENCES trip(id) ON DELETE CASCADE,
    tanggal TEXT NOT NULL,
    jam TEXT NOT NULL,
    judul TEXT NOT NULL,
    oleh_id INTEGER NOT NULL REFERENCES pengguna(id)
);
CREATE TABLE IF NOT EXISTS pengeluaran (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL REFERENCES trip(id) ON DELETE CASCADE,
    judul TEXT NOT NULL,
    jumlah INTEGER NOT NULL,
    dibayar_oleh INTEGER NOT NULL REFERENCES pengguna(id),
    dibagi_ke TEXT NOT NULL,
    kategori TEXT,
    oleh_id INTEGER NOT NULL REFERENCES pengguna(id),
    dibuat TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pelunasan (
    trip_id INTEGER NOT NULL REFERENCES trip(id) ON DELETE CASCADE,
    dari_id INTEGER NOT NULL,
    ke_id INTEGER NOT NULL,
    PRIMARY KEY (trip_id, dari_id, ke_id)
);
CREATE TABLE IF NOT EXISTS hari_tutup (
    kegiatan_id TEXT NOT NULL,
    tanggal TEXT NOT NULL,
    oleh_id INTEGER NOT NULL REFERENCES pengguna(id),
    PRIMARY KEY (kegiatan_id, tanggal)
);
CREATE TABLE IF NOT EXISTS payout (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL UNIQUE REFERENCES item(id) ON DELETE CASCADE,
    kegiatan_id TEXT NOT NULL,
    jumlah INTEGER NOT NULL,
    tanggal TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stempel (
    pengguna_id INTEGER NOT NULL REFERENCES pengguna(id) ON DELETE CASCADE,
    kegiatan_id TEXT NOT NULL,
    tanggal TEXT NOT NULL,
    kode TEXT NOT NULL,
    PRIMARY KEY (pengguna_id, kegiatan_id)
);
CREATE TABLE IF NOT EXISTS host_kelola (
    host_id TEXT PRIMARY KEY,
    pengguna_id INTEGER NOT NULL REFERENCES pengguna(id) ON DELETE CASCADE,
    sejak TEXT NOT NULL
);
"""


def _sekarang():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hari_ini():
    return datetime.now(WIB).date()


def _tgl(v, nama):
    try:
        return date.fromisoformat(v).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"{nama} harus berformat YYYY-MM-DD")


# ---------- skema permintaan ----------
class TripBaru(BaseModel):
    nama: str = Field(default="Trip Bali", min_length=1, max_length=80)
    tanggal_mulai: str
    tanggal_akhir: str

    @field_validator("tanggal_mulai", "tanggal_akhir")
    @classmethod
    def cek_tgl(cls, v, info):
        return _tgl(v, info.field_name)


class TripUbah(BaseModel):
    nama: Optional[str] = Field(default=None, min_length=1, max_length=80)
    tanggal_mulai: Optional[str] = None
    tanggal_akhir: Optional[str] = None
    bendahara_id: Optional[int] = None

    @field_validator("tanggal_mulai", "tanggal_akhir")
    @classmethod
    def cek_tgl(cls, v, info):
        return None if v is None else _tgl(v, info.field_name)


class Gabung(BaseModel):
    kode: str = Field(min_length=4, max_length=40)


class HariSibuk(BaseModel):
    hari_sibuk: List[str] = Field(default_factory=list, max_length=60)

    @field_validator("hari_sibuk")
    @classmethod
    def cek(cls, v):
        return sorted({_tgl(x, "hari_sibuk") for x in v})


class ItemBaru(BaseModel):
    kegiatan_id: str = Field(min_length=1, max_length=10)
    tanggal: str
    jam: Optional[str] = None  # kosong: jam mulai pertama kegiatan itu
    jumlah_orang: Optional[int] = Field(default=None, ge=1, le=50)

    @field_validator("tanggal")
    @classmethod
    def cek_tgl(cls, v):
        return _tgl(v, "tanggal")

    @field_validator("jam")
    @classmethod
    def cek_jam(cls, v):
        if v is not None and not POLA_JAM.match(v):
            raise ValueError("jam harus berformat HH:MM")
        return v


class AcaraBaru(BaseModel):
    tanggal: str
    jam: str = "09:00"
    judul: str = Field(min_length=1, max_length=120)

    @field_validator("tanggal")
    @classmethod
    def cek_tgl(cls, v):
        return _tgl(v, "tanggal")

    @field_validator("jam")
    @classmethod
    def cek_jam(cls, v):
        if not POLA_JAM.match(v):
            raise ValueError("jam harus berformat HH:MM")
        return v


class PengeluaranBaru(BaseModel):
    judul: str = Field(min_length=1, max_length=120)
    jumlah: int = Field(gt=0, le=1_000_000_000)
    dibayar_oleh: int
    dibagi_ke: List[int] = Field(min_length=1, max_length=50)
    kategori: Optional[str] = Field(default=None, max_length=40)


class Lunas(BaseModel):
    dari_id: int
    ke_id: int
    lunas: bool = True


class Bayar(BaseModel):
    item_ids: Optional[List[int]] = Field(default=None, max_length=100)  # kosong: semua item disetujui


class Keputusan(BaseModel):
    setuju: bool


class Tutup(BaseModel):
    kegiatan_id: str = Field(min_length=1, max_length=10)
    tanggal: str
    tutup: bool = True

    @field_validator("tanggal")
    @classmethod
    def cek_tgl(cls, v):
        return _tgl(v, "tanggal")


class Klaim(BaseModel):
    host_id: str = Field(min_length=1, max_length=10)


class AturHost(BaseModel):
    email: str = Field(max_length=254)
    host_id: str = Field(min_length=1, max_length=10)


class Stempel(BaseModel):
    kode: str = Field(min_length=4, max_length=20)


class Plus(BaseModel):
    uji_coba: bool = False


# ---------- logika murni (dites terpisah) ----------
def hitung_pelunasan(anggota_ids, pengeluaran):
    """pengeluaran: [{jumlah, dibayar_oleh, dibagi_ke}]. Sama dengan PS.settle() di store.js."""
    bal = {a: {"dibayar": 0.0, "bagian": 0.0} for a in anggota_ids}
    for e in pengeluaran:
        sp = [x for x in e["dibagi_ke"] if x in bal]
        if not sp:
            continue
        if e["dibayar_oleh"] in bal:
            bal[e["dibayar_oleh"]]["dibayar"] += e["jumlah"]
        for x in sp:
            bal[x]["bagian"] += e["jumlah"] / len(sp)
    net = [{"id": a, "saldo": round(bal[a]["dibayar"] - bal[a]["bagian"])} for a in anggota_ids]
    utang = sorted(({"id": n["id"], "v": -n["saldo"]} for n in net if n["saldo"] < 0), key=lambda x: -x["v"])
    piutang = sorted(({"id": n["id"], "v": n["saldo"]} for n in net if n["saldo"] > 0), key=lambda x: -x["v"])
    tx, i, j = [], 0, 0
    while i < len(utang) and j < len(piutang):
        x = min(utang[i]["v"], piutang[j]["v"])
        if x > 0:
            tx.append({"dari_id": utang[i]["id"], "ke_id": piutang[j]["id"], "jumlah": x})
        utang[i]["v"] -= x
        piutang[j]["v"] -= x
        if utang[i]["v"] <= 0:
            i += 1
        if piutang[j]["v"] <= 0:
            j += 1
    return {"saldo": net, "transfer": tx}


# ---------- router ----------
def pasang(app, db, katalog, pengguna_aktif, admin_emails=(), mode_demo=True):
    """katalog: {id: kegiatan} untuk kegiatan yang siap direkomendasikan (K01, ...).
    pengguna_aktif: dependency FastAPI yang mengembalikan pengguna login."""
    with db.koneksi() as c:
        c.executescript(SKEMA)
        ada = {r["name"] for r in c.execute("PRAGMA table_info(pengguna)")}
        if "plus_sampai" not in ada:
            c.execute("ALTER TABLE pengguna ADD COLUMN plus_sampai TEXT")
        if "uji_coba_dipakai" not in ada:
            c.execute("ALTER TABLE pengguna ADD COLUMN uji_coba_dipakai INTEGER NOT NULL DEFAULT 0")

    def kegiatan(kid):
        k = katalog.get(kid)
        if not k:
            raise HTTPException(404, f"Kegiatan {kid} tidak ada atau belum siap dipesan.")
        return k

    # ---- pembantu akses ----
    def trip_milik(c, trip_id, p):
        t = c.execute("SELECT * FROM trip WHERE id = ?", (trip_id,)).fetchone()
        ang = c.execute("SELECT 1 FROM anggota WHERE trip_id = ? AND pengguna_id = ?", (trip_id, p["id"])).fetchone()
        if not t or not ang:
            raise HTTPException(404, "Trip tidak ditemukan.")
        return dict(t)

    def host_saja(p):
        if (p.get("peran") or "wisatawan") != "host":
            raise HTTPException(403, "Hanya akun host yang bisa melakukan ini.")
        return p

    def host_ids(c, p):
        return {r["host_id"] for r in c.execute("SELECT host_id FROM host_kelola WHERE pengguna_id = ?", (p["id"],))}

    def kegiatan_host(c, p):
        hid = host_ids(c, p)
        return {k["id"] for k in katalog.values() if k.get("host_id") in hid}

    def nama_pendek(nama):
        bagian = (nama or "").split()
        if not bagian:
            return "Tamu"
        return bagian[0] + (f" {bagian[1][0]}." if len(bagian) > 1 else "")

    def item_dict(r):
        d = dict(r)
        k = katalog.get(d["kegiatan_id"], {})
        d["nama_kegiatan"] = k.get("nama")
        d["harga_per_orang"] = k.get("harga_per_orang")
        d["biaya"] = (k.get("harga_per_orang") or 0) * d["jumlah_orang"]
        if k.get("demo"):
            d["demo"] = True
        d.pop("kode_hadir", None)  # kode hadir hanya dilihat host
        return d

    def tutup_pada(c, kid, tgl):
        """Alasan tutup (teks) atau None. Dua sumber: hari tutup dari host, dan purnama/tilem."""
        if c.execute("SELECT 1 FROM hari_tutup WHERE kegiatan_id = ? AND tanggal = ?", (kid, tgl)).fetchone():
            return "Kegiatan ini tutup pada tanggal tersebut."
        if katalog.get(kid, {}).get("tutup_purnama_tilem"):
            fase = fase_pada(tgl)
            if fase:
                return f"Kegiatan ini tutup saat {fase} ({tgl}). Pilih tanggal lain."
        return None

    def terisi(c, kid, tgl, jam, kecuali=None):
        r = c.execute("SELECT COALESCE(SUM(jumlah_orang), 0) AS n FROM item WHERE kegiatan_id = ? AND tanggal = ? "
                      "AND jam = ? AND status IN ('disetujui', 'lunas') AND id != ?",
                      (kid, tgl, jam, kecuali or -1)).fetchone()
        return r["n"]

    def isi_trip(c, t, p):
        anggota = [dict(r) for r in c.execute(
            "SELECT a.pengguna_id AS id, u.nama, a.hari_sibuk, a.bergabung FROM anggota a "
            "JOIN pengguna u ON u.id = a.pengguna_id WHERE a.trip_id = ? ORDER BY a.bergabung", (t["id"],))]
        for a in anggota:
            a["hari_sibuk"] = json.loads(a["hari_sibuk"])
            a["saya"] = a["id"] == p["id"]
        items = [item_dict(r) for r in c.execute(
            "SELECT * FROM item WHERE trip_id = ? ORDER BY tanggal, jam", (t["id"],))]
        acara = [dict(r) for r in c.execute("SELECT * FROM acara WHERE trip_id = ? ORDER BY tanggal, jam", (t["id"],))]
        peng = []
        for r in c.execute("SELECT * FROM pengeluaran WHERE trip_id = ? ORDER BY id", (t["id"],)):
            d = dict(r)
            d["dibagi_ke"] = json.loads(d["dibagi_ke"])
            peng.append(d)
        return {**t, "anggota": anggota, "items": items, "acara": acara, "pengeluaran": peng}

    def semua_pengeluaran(trip):
        """Item kegiatan (selain ditolak) otomatis jadi pengeluaran, dibayar bendahara, dibagi ke anggota."""
        ids = [a["id"] for a in trip["anggota"]]
        out = []
        for it in trip["items"]:
            if it["status"] == "ditolak":
                continue
            out.append({"judul": it["nama_kegiatan"], "jumlah": it["biaya"], "dibayar_oleh": trip["bendahara_id"],
                        "dibagi_ke": ids[:it["jumlah_orang"]] or ids, "otomatis": True, "item_id": it["id"],
                        "status": it["status"]})
        out += [{**e, "otomatis": False} for e in trip["pengeluaran"]]
        return out

    # ================= trip =================
    @app.post("/api/trips", status_code=201, tags=["trip"])
    def buat_trip(d: TripBaru, p=Depends(pengguna_aktif)):
        if d.tanggal_akhir < d.tanggal_mulai:
            raise HTTPException(422, "tanggal_akhir tidak boleh sebelum tanggal_mulai.")
        with db.koneksi() as c:
            kode = "bali-" + secrets.token_hex(3)
            cur = c.execute("INSERT INTO trip (nama, tanggal_mulai, tanggal_akhir, bendahara_id, kode, dibuat) "
                            "VALUES (?, ?, ?, ?, ?, ?)", (d.nama.strip(), d.tanggal_mulai, d.tanggal_akhir,
                                                          p["id"], kode, _sekarang()))
            c.execute("INSERT INTO anggota (trip_id, pengguna_id, bergabung) VALUES (?, ?, ?)",
                      (cur.lastrowid, p["id"], _sekarang()))
            return isi_trip(c, trip_milik(c, cur.lastrowid, p), p)

    @app.get("/api/trips", tags=["trip"])
    def daftar_trip(p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            return [dict(r) for r in c.execute(
                "SELECT t.id, t.nama, t.tanggal_mulai, t.tanggal_akhir, t.kode, t.bendahara_id FROM trip t "
                "JOIN anggota a ON a.trip_id = t.id WHERE a.pengguna_id = ? ORDER BY t.tanggal_mulai", (p["id"],))]

    @app.get("/api/trips/{trip_id}", tags=["trip"])
    def detail_trip(trip_id: int, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            return isi_trip(c, trip_milik(c, trip_id, p), p)

    @app.patch("/api/trips/{trip_id}", tags=["trip"])
    def ubah_trip(trip_id: int, d: TripUbah, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            t = trip_milik(c, trip_id, p)
            baru = {k: v for k, v in d.model_dump().items() if v is not None}
            if "nama" in baru:
                baru["nama"] = baru["nama"].strip()
            mulai = baru.get("tanggal_mulai", t["tanggal_mulai"])
            akhir = baru.get("tanggal_akhir", t["tanggal_akhir"])
            if akhir < mulai:
                raise HTTPException(422, "tanggal_akhir tidak boleh sebelum tanggal_mulai.")
            if "bendahara_id" in baru and not c.execute(
                    "SELECT 1 FROM anggota WHERE trip_id = ? AND pengguna_id = ?", (trip_id, baru["bendahara_id"])).fetchone():
                raise HTTPException(422, "Bendahara harus anggota trip.")
            for k, v in baru.items():
                c.execute(f"UPDATE trip SET {k} = ? WHERE id = ?", (v, trip_id))  # k dari daftar field model
            return isi_trip(c, trip_milik(c, trip_id, p), p)

    @app.post("/api/trips/join", tags=["trip"])
    def gabung(d: Gabung, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            t = c.execute("SELECT * FROM trip WHERE kode = ?", (d.kode.strip().lower(),)).fetchone()
            if not t:
                raise HTTPException(404, "Kode undangan tidak ditemukan.")
            c.execute("INSERT OR IGNORE INTO anggota (trip_id, pengguna_id, bergabung) VALUES (?, ?, ?)",
                      (t["id"], p["id"], _sekarang()))
            return isi_trip(c, trip_milik(c, t["id"], p), p)

    @app.put("/api/trips/{trip_id}/saya", tags=["trip"])
    def hari_sibuk(trip_id: int, d: HariSibuk, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            trip_milik(c, trip_id, p)
            c.execute("UPDATE anggota SET hari_sibuk = ? WHERE trip_id = ? AND pengguna_id = ?",
                      (json.dumps(d.hari_sibuk), trip_id, p["id"]))
            return {"hari_sibuk": d.hari_sibuk}

    # ================= item kegiatan =================
    @app.post("/api/trips/{trip_id}/items", status_code=201, tags=["trip"])
    def tambah_item(trip_id: int, d: ItemBaru, p=Depends(pengguna_aktif)):
        k = kegiatan(d.kegiatan_id)
        with db.koneksi() as c:
            t = trip_milik(c, trip_id, p)
            if d.tanggal < hari_ini().isoformat():
                raise HTTPException(422, "Tanggal kegiatan sudah lewat.")
            dupe = c.execute("SELECT id FROM item WHERE trip_id = ? AND kegiatan_id = ? AND tanggal = ? "
                             "AND status != 'ditolak'", (trip_id, d.kegiatan_id, d.tanggal)).fetchone()
            if dupe:
                raise HTTPException(409, "Kegiatan ini sudah ada di tanggal yang sama.")
            alasan = tutup_pada(c, d.kegiatan_id, d.tanggal)
            if alasan:
                raise HTTPException(409, alasan)
            orang = d.jumlah_orang or c.execute("SELECT COUNT(*) AS n FROM anggota WHERE trip_id = ?",
                                                (trip_id,)).fetchone()["n"]
            if orang > k["kuota"]:
                raise HTTPException(422, f"Kuota kegiatan ini {k['kuota']} orang per sesi.")
            cur = c.execute("INSERT INTO item (trip_id, kegiatan_id, tanggal, jam, jumlah_orang, status, oleh_id, "
                            "dibuat, diperbarui) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
                            (trip_id, d.kegiatan_id, d.tanggal, d.jam or (k.get("jam_mulai") or ["09:00"])[0], orang,
                             p["id"], _sekarang(), _sekarang()))
            # rentang trip ikut melebar, sama seperti store.js
            if d.tanggal < t["tanggal_mulai"]:
                c.execute("UPDATE trip SET tanggal_mulai = ? WHERE id = ?", (d.tanggal, trip_id))
            if d.tanggal > t["tanggal_akhir"]:
                c.execute("UPDATE trip SET tanggal_akhir = ? WHERE id = ?", (d.tanggal, trip_id))
            return item_dict(c.execute("SELECT * FROM item WHERE id = ?", (cur.lastrowid,)).fetchone())

    def ambil_item(c, trip_id, item_id):
        r = c.execute("SELECT * FROM item WHERE id = ? AND trip_id = ?", (item_id, trip_id)).fetchone()
        if not r:
            raise HTTPException(404, "Item tidak ditemukan.")
        return dict(r)

    @app.delete("/api/trips/{trip_id}/items/{item_id}", status_code=204, tags=["trip"])
    def hapus_item(trip_id: int, item_id: int, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            trip_milik(c, trip_id, p)
            it = ambil_item(c, trip_id, item_id)
            if it["status"] in ("disetujui", "lunas"):
                raise HTTPException(409, "Item yang sudah disetujui atau lunas tidak bisa dihapus.")
            c.execute("DELETE FROM item WHERE id = ?", (item_id,))

    @app.post("/api/trips/{trip_id}/items/{item_id}/request", tags=["trip"])
    def ajukan(trip_id: int, item_id: int, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            trip_milik(c, trip_id, p)
            it = ambil_item(c, trip_id, item_id)
            if it["status"] != "draft":
                raise HTTPException(409, f"Hanya item draft yang bisa diajukan (status sekarang: {it['status']}).")
            if it["tanggal"] < hari_ini().isoformat():
                raise HTTPException(422, "Tanggal kegiatan sudah lewat.")
            alasan = tutup_pada(c, it["kegiatan_id"], it["tanggal"])
            if alasan:
                raise HTTPException(409, alasan)
            c.execute("UPDATE item SET status = 'diajukan', diperbarui = ? WHERE id = ?", (_sekarang(), item_id))
            return item_dict(c.execute("SELECT * FROM item WHERE id = ?", (item_id,)).fetchone())

    # ================= acara pribadi =================
    @app.post("/api/trips/{trip_id}/events", status_code=201, tags=["trip"])
    def tambah_acara(trip_id: int, d: AcaraBaru, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            trip_milik(c, trip_id, p)
            cur = c.execute("INSERT INTO acara (trip_id, tanggal, jam, judul, oleh_id) VALUES (?, ?, ?, ?, ?)",
                            (trip_id, d.tanggal, d.jam, d.judul.strip(), p["id"]))
            return dict(c.execute("SELECT * FROM acara WHERE id = ?", (cur.lastrowid,)).fetchone())

    @app.delete("/api/trips/{trip_id}/events/{acara_id}", status_code=204, tags=["trip"])
    def hapus_acara(trip_id: int, acara_id: int, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            trip_milik(c, trip_id, p)
            if not c.execute("DELETE FROM acara WHERE id = ? AND trip_id = ?", (acara_id, trip_id)).rowcount:
                raise HTTPException(404, "Acara tidak ditemukan.")

    # ================= patungan =================
    @app.post("/api/trips/{trip_id}/expenses", status_code=201, tags=["patungan"])
    def tambah_pengeluaran(trip_id: int, d: PengeluaranBaru, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            trip_milik(c, trip_id, p)
            ang = {r["pengguna_id"] for r in c.execute("SELECT pengguna_id FROM anggota WHERE trip_id = ?", (trip_id,))}
            if d.dibayar_oleh not in ang or not set(d.dibagi_ke) <= ang:
                raise HTTPException(422, "Pembayar dan penanggung harus anggota trip.")
            cur = c.execute("INSERT INTO pengeluaran (trip_id, judul, jumlah, dibayar_oleh, dibagi_ke, kategori, "
                            "oleh_id, dibuat) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (trip_id, d.judul.strip(), d.jumlah, d.dibayar_oleh, json.dumps(sorted(set(d.dibagi_ke))),
                             d.kategori, p["id"], _sekarang()))
            r = dict(c.execute("SELECT * FROM pengeluaran WHERE id = ?", (cur.lastrowid,)).fetchone())
            r["dibagi_ke"] = json.loads(r["dibagi_ke"])
            return r

    @app.delete("/api/trips/{trip_id}/expenses/{peng_id}", status_code=204, tags=["patungan"])
    def hapus_pengeluaran(trip_id: int, peng_id: int, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            trip_milik(c, trip_id, p)
            if not c.execute("DELETE FROM pengeluaran WHERE id = ? AND trip_id = ?", (peng_id, trip_id)).rowcount:
                raise HTTPException(404, "Pengeluaran tidak ditemukan.")

    @app.get("/api/trips/{trip_id}/settlement", tags=["patungan"])
    def pelunasan(trip_id: int, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            trip = isi_trip(c, trip_milik(c, trip_id, p), p)
            sudah = {(r["dari_id"], r["ke_id"]) for r in c.execute(
                "SELECT dari_id, ke_id FROM pelunasan WHERE trip_id = ?", (trip_id,))}
        semua = semua_pengeluaran(trip)
        hasil = hitung_pelunasan([a["id"] for a in trip["anggota"]], semua)
        nama = {a["id"]: a["nama"] for a in trip["anggota"]}
        for s in hasil["saldo"]:
            s["nama"] = nama.get(s["id"])
        for t in hasil["transfer"]:
            t["dari_nama"], t["ke_nama"] = nama.get(t["dari_id"]), nama.get(t["ke_id"])
            t["lunas"] = (t["dari_id"], t["ke_id"]) in sudah
        return {**hasil, "total": sum(e["jumlah"] for e in semua), "pengeluaran": semua}

    @app.post("/api/trips/{trip_id}/settlement", tags=["patungan"])
    def tandai_lunas(trip_id: int, d: Lunas, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            trip_milik(c, trip_id, p)
            if d.lunas:
                c.execute("INSERT OR IGNORE INTO pelunasan (trip_id, dari_id, ke_id) VALUES (?, ?, ?)",
                          (trip_id, d.dari_id, d.ke_id))
            else:
                c.execute("DELETE FROM pelunasan WHERE trip_id = ? AND dari_id = ? AND ke_id = ?",
                          (trip_id, d.dari_id, d.ke_id))
        return {"ok": True}

    # ================= pembayaran (simulasi) =================
    @app.post("/api/trips/{trip_id}/pay", tags=["pembayaran"])
    def bayar(trip_id: int, d: Bayar, p=Depends(pengguna_aktif)):
        """SIMULASI: item disetujui menjadi lunas, payout dicatat untuk host. Tidak ada uang yang berpindah."""
        with db.koneksi() as c:
            trip_milik(c, trip_id, p)
            q = "SELECT * FROM item WHERE trip_id = ? AND status = 'disetujui'"
            rows = [dict(r) for r in c.execute(q, (trip_id,))]
            if d.item_ids:
                diminta = set(d.item_ids)
                semua = {r["id"]: r["status"] for r in c.execute("SELECT id, status FROM item WHERE trip_id = ?",
                                                                  (trip_id,))}
                salah = [i for i in diminta if semua.get(i) != "disetujui"]
                if salah:
                    raise HTTPException(409, "Hanya item yang sudah disetujui host yang bisa dibayar.")
                rows = [r for r in rows if r["id"] in diminta]
            if not rows:
                raise HTTPException(409, "Belum ada item yang disetujui host untuk dibayar.")
            total = 0
            for r in rows:
                biaya = (katalog.get(r["kegiatan_id"], {}).get("harga_per_orang") or 0) * r["jumlah_orang"]
                total += biaya
                kode = "PA-" + secrets.token_hex(3).upper()
                c.execute("UPDATE item SET status = 'lunas', kode_hadir = ?, diperbarui = ? WHERE id = ?",
                          (kode, _sekarang(), r["id"]))
                c.execute("INSERT OR IGNORE INTO payout (item_id, kegiatan_id, jumlah, tanggal) VALUES (?, ?, ?, ?)",
                          (r["id"], r["kegiatan_id"], biaya, hari_ini().isoformat()))
            return {"simulasi": True, "dibayar": [r["id"] for r in rows], "total": total}

    # ================= host =================
    @app.get("/api/host/kegiatan", tags=["host"])
    def kegiatan_saya(p=Depends(pengguna_aktif)):
        host_saja(p)
        with db.koneksi() as c:
            kid = kegiatan_host(c, p)
            tutup = {}
            for r in c.execute("SELECT kegiatan_id, tanggal FROM hari_tutup ORDER BY tanggal"):
                if r["kegiatan_id"] in kid:
                    tutup.setdefault(r["kegiatan_id"], []).append(r["tanggal"])
            return {"host_ids": sorted(host_ids(c, p)),
                    "kegiatan": [{"id": k, "nama": katalog[k]["nama"], "kuota": katalog[k]["kuota"],
                                  "hari_tutup": tutup.get(k, []), "jam_mulai": katalog[k].get("jam_mulai") or [],
                                  "tutup_purnama_tilem": bool(katalog[k].get("tutup_purnama_tilem"))}
                                 for k in sorted(kid)]}

    @app.post("/api/host/klaim", tags=["host"])
    def klaim(d: Klaim, p=Depends(pengguna_aktif)):
        """MODE DEMO: akun host mengklaim satu ID host di sheet (H01, ...) yang belum diklaim.
        Di luar mode demo, penetapan dilakukan admin lewat /api/admin/host."""
        host_saja(p)
        if not mode_demo:
            raise HTTPException(403, "Penetapan host dilakukan admin.")
        if not any(k.get("host_id") == d.host_id for k in katalog.values()):
            raise HTTPException(404, "ID host tidak dikenal.")
        with db.koneksi() as c:
            r = c.execute("SELECT pengguna_id FROM host_kelola WHERE host_id = ?", (d.host_id,)).fetchone()
            if r and r["pengguna_id"] != p["id"]:
                raise HTTPException(409, "ID host ini sudah dikelola akun lain.")
            c.execute("INSERT OR IGNORE INTO host_kelola (host_id, pengguna_id, sejak) VALUES (?, ?, ?)",
                      (d.host_id, p["id"], _sekarang()))
        return kegiatan_saya(p)

    @app.post("/api/admin/host", tags=["host"])
    def atur_host(d: AturHost, p=Depends(pengguna_aktif)):
        if p["email"] not in admin_emails:
            raise HTTPException(403, "Hanya admin.")
        with db.koneksi() as c:
            u = c.execute("SELECT id, peran FROM pengguna WHERE email = ?", (d.email.strip().lower(),)).fetchone()
            if not u or u["peran"] != "host":
                raise HTTPException(404, "Akun host dengan email itu tidak ditemukan.")
            c.execute("INSERT OR REPLACE INTO host_kelola (host_id, pengguna_id, sejak) VALUES (?, ?, ?)",
                      (d.host_id, u["id"], _sekarang()))
        return {"ok": True}

    @app.get("/api/host/requests", tags=["host"])
    def permintaan_masuk(p=Depends(pengguna_aktif)):
        host_saja(p)
        with db.koneksi() as c:
            kid = kegiatan_host(c, p)
            if not kid:
                return []
            tanda = ",".join("?" * len(kid))
            rows = c.execute(
                f"SELECT i.*, u.nama AS nama_pengaju FROM item i JOIN pengguna u ON u.id = i.oleh_id "
                f"WHERE i.kegiatan_id IN ({tanda}) AND i.status != 'draft' ORDER BY i.tanggal, i.jam",
                tuple(sorted(kid))).fetchall()
            out = []
            for r in rows:
                d = item_dict(r)
                d["nama_pengaju"] = nama_pendek(r["nama_pengaju"])  # tanpa email dan nama lengkap
                d["kode_hadir"] = r["kode_hadir"]
                d.pop("trip_id", None)
                d.pop("oleh_id", None)
                d["terisi_sesi"] = terisi(c, r["kegiatan_id"], r["tanggal"], r["jam"])
                d["kuota"] = katalog[r["kegiatan_id"]]["kuota"]
                out.append(d)
            return out

    @app.post("/api/host/requests/{item_id}/decision", tags=["host"])
    def putuskan(item_id: int, d: Keputusan, p=Depends(pengguna_aktif)):
        host_saja(p)
        with db.koneksi() as c:
            r = c.execute("SELECT * FROM item WHERE id = ?", (item_id,)).fetchone()
            if not r or r["kegiatan_id"] not in kegiatan_host(c, p):
                raise HTTPException(404, "Permintaan tidak ditemukan.")
            if r["status"] != "diajukan":
                raise HTTPException(409, f"Permintaan ini sudah {r['status']}.")
            status = "ditolak"
            if d.setuju:
                kuota = katalog[r["kegiatan_id"]]["kuota"]
                if terisi(c, r["kegiatan_id"], r["tanggal"], r["jam"], kecuali=item_id) + r["jumlah_orang"] > kuota:
                    raise HTTPException(409, f"Kuota sesi ini ({kuota} orang) tidak cukup.")
                status = "disetujui"
            c.execute("UPDATE item SET status = ?, diperbarui = ? WHERE id = ?", (status, _sekarang(), item_id))
            return item_dict(c.execute("SELECT * FROM item WHERE id = ?", (item_id,)).fetchone())

    @app.post("/api/host/closed", tags=["host"])
    def atur_tutup(d: Tutup, p=Depends(pengguna_aktif)):
        host_saja(p)
        with db.koneksi() as c:
            if d.kegiatan_id not in kegiatan_host(c, p):
                raise HTTPException(403, "Kegiatan ini bukan milik akunmu.")
            if d.tutup:
                c.execute("INSERT OR IGNORE INTO hari_tutup (kegiatan_id, tanggal, oleh_id) VALUES (?, ?, ?)",
                          (d.kegiatan_id, d.tanggal, p["id"]))
            else:
                c.execute("DELETE FROM hari_tutup WHERE kegiatan_id = ? AND tanggal = ?", (d.kegiatan_id, d.tanggal))
        return {"ok": True}

    @app.get("/api/kegiatan/{kegiatan_id}/tutup", tags=["host"])
    def lihat_tutup(kegiatan_id: str):
        kegiatan(kegiatan_id)
        with db.koneksi() as c:
            return [r["tanggal"] for r in c.execute(
                "SELECT tanggal FROM hari_tutup WHERE kegiatan_id = ? ORDER BY tanggal", (kegiatan_id,))]

    @app.get("/api/kalender", tags=["kalender"])
    def kalender(dari: Optional[str] = None, sampai: Optional[str] = None):
        """Purnama dan tilem (perkiraan astronomis, waktu Bali) antara dua tanggal, maksimal 400 hari.
        Default: hari ini sampai 120 hari ke depan."""
        try:
            a = date.fromisoformat(dari) if dari else hari_ini()
            b = date.fromisoformat(sampai) if sampai else a + timedelta(days=120)
        except ValueError:
            raise HTTPException(422, "dari dan sampai harus berformat YYYY-MM-DD.")
        if b < a or (b - a).days > 400:
            raise HTTPException(422, "Rentang tanggal harus 0 sampai 400 hari.")
        return {"perkiraan": True, "catatan": "Dihitung astronomis (Meeus). Kalender Bali bisa selisih satu hari.",
                "fase": fase_bulan(a, b),
                "kegiatan_tutup_purnama_tilem": sorted(k for k, v in katalog.items() if v.get("tutup_purnama_tilem"))}

    @app.get("/api/host/payouts", tags=["host"])
    def payout_host(p=Depends(pengguna_aktif)):
        host_saja(p)
        with db.koneksi() as c:
            kid = kegiatan_host(c, p)
            rows = [dict(r) for r in c.execute("SELECT * FROM payout ORDER BY tanggal DESC") if r["kegiatan_id"] in kid]
        return {"simulasi": True, "total": sum(r["jumlah"] for r in rows), "payout": rows}

    # ================= paspor =================
    @app.get("/api/passport", tags=["paspor"])
    def paspor(p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            rows = [dict(r) for r in c.execute("SELECT kegiatan_id, tanggal, kode FROM stempel WHERE pengguna_id = ? "
                                               "ORDER BY tanggal", (p["id"],))]
        for r in rows:
            r["nama_kegiatan"] = katalog.get(r["kegiatan_id"], {}).get("nama")
        return rows

    @app.post("/api/passport/stamp", status_code=201, tags=["paspor"])
    def stempel(d: Stempel, p=Depends(pengguna_aktif)):
        with db.koneksi() as c:
            r = c.execute("SELECT i.* FROM item i JOIN anggota a ON a.trip_id = i.trip_id AND a.pengguna_id = ? "
                          "WHERE i.kode_hadir = ? AND i.status = 'lunas'", (p["id"], d.kode.strip().upper())).fetchone()
            if not r:
                raise HTTPException(404, "Kode hadir tidak cocok dengan kegiatan lunas di tripmu.")
            if c.execute("SELECT 1 FROM stempel WHERE pengguna_id = ? AND kegiatan_id = ?",
                         (p["id"], r["kegiatan_id"])).fetchone():
                raise HTTPException(409, "Kamu sudah punya stempel untuk kegiatan ini.")
            c.execute("INSERT INTO stempel (pengguna_id, kegiatan_id, tanggal, kode) VALUES (?, ?, ?, ?)",
                      (p["id"], r["kegiatan_id"], hari_ini().isoformat(), r["kode_hadir"]))
            return {"kegiatan_id": r["kegiatan_id"], "nama_kegiatan": katalog.get(r["kegiatan_id"], {}).get("nama"),
                    "tanggal": hari_ini().isoformat()}

    # ================= paket Plus (simulasi) =================
    @app.post("/api/akun/plus", tags=["akun"])
    def plus(d: Plus, p=Depends(pengguna_aktif)):
        """SIMULASI pembayaran Plus (Rp49.000 per bulan). uji_coba=true: 7 hari gratis, sekali per akun."""
        with db.koneksi() as c:
            u = dict(c.execute("SELECT * FROM pengguna WHERE id = ?", (p["id"],)).fetchone())
            dasar = max(hari_ini(), date.fromisoformat(u["plus_sampai"])) if u.get("plus_sampai") else hari_ini()
            if d.uji_coba:
                if u["uji_coba_dipakai"]:
                    raise HTTPException(409, "Uji coba Plus sudah pernah dipakai.")
                sampai = dasar + timedelta(days=7)
                c.execute("UPDATE pengguna SET plus_sampai = ?, uji_coba_dipakai = 1 WHERE id = ?",
                          (sampai.isoformat(), p["id"]))
            else:
                sampai = dasar + timedelta(days=30)
                c.execute("UPDATE pengguna SET plus_sampai = ? WHERE id = ?", (sampai.isoformat(), p["id"]))
        return {"simulasi": True, "paket": "plus", "plus_sampai": sampai.isoformat(),
                "harga_per_bulan": 49000, "uji_coba": d.uji_coba}


def paket_efektif(p):
    """'plus' kalau ditetapkan permanen, atau masa Plus (uji coba/langganan simulasi) belum habis."""
    if (p.get("paket") or "gratis") == "plus":
        return "plus"
    sampai = p.get("plus_sampai")
    if sampai and sampai >= hari_ini().isoformat():
        return "plus"
    return "gratis"
