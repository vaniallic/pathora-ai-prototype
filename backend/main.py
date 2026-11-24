"""Server API Pathora (FastAPI).

Jalankan dari folder repo:
    uvicorn backend.main:app --reload --port 8000

Dokumentasi API otomatis: http://localhost:8000/docs
Halaman uji sederhana:    http://localhost:8000/
"""
import logging
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from . import config
from .db import Database
from .keamanan import HASH_PALSU, PembatasLogin, baca_token, buat_token, cek_password, hash_password

sys.path.insert(0, str(config.AKAR))
from asisten import jawab, muat_jarak  # noqa: E402
from load_data import (HOST_KOLOM, KEGIATAN_KOLOM, baca_csv, bersihkan_kegiatan,  # noqa: E402
                       periksa, terapkan_isian_demo)

log = logging.getLogger("pathora")

# Kolom kegiatan yang aman ditampilkan ke publik (kontak host dan catatan internal tidak ikut).
KOLOM_PUBLIK = ["id", "nama", "desa", "tema", "harga_per_orang", "durasi_jam", "kuota", "tingkat_kesulitan",
                "cocok_untuk", "fasilitas", "titik_kumpul", "cara_ke_sana", "aturan_budaya", "perlengkapan",
                "cuaca_buruk", "hari_tutup", "demo"]
POLA_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- skema permintaan dan balasan ----------
class Daftar(BaseModel):
    nama: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def email_valid(cls, v):
        v = v.strip().lower()
        if not POLA_EMAIL.match(v):
            raise ValueError("format email tidak valid")
        return v

    @field_validator("nama")
    @classmethod
    def nama_rapi(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("nama tidak boleh kosong")
        return v


class Masuk(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class PermintaanRencana(BaseModel):
    teks: str = Field(min_length=1, max_length=2000)
    # Kalau asisten sebelumnya bertanya balik (tipe "tanya"), kirim id permintaan itu di sini
    # supaya jawaban pengguna digabung dengan permintaan awalnya.
    lanjutan_dari: Optional[int] = None


def _publik(p):
    return {"id": p["id"], "nama": p["nama"], "email": p["email"], "dibuat": p["dibuat"]}


def muat_kegiatan(demo, masa_berlaku_hari=None):
    """Membaca CSV, memeriksa kesiapan, mengembalikan (kegiatan_siap, semua_kegiatan, laporan)."""
    kegiatan = bersihkan_kegiatan(baca_csv(config.DATA["kegiatan"], KEGIATAN_KOLOM))
    host = baca_csv(config.DATA["host"], HOST_KOLOM)
    if demo:
        if config.DATA["isian_demo"].exists():
            terapkan_isian_demo(kegiatan, config.DATA["isian_demo"])
        else:
            for k in kegiatan:
                k["demo"] = True
    laporan = periksa(kegiatan, host, date.today(), masa_berlaku_hari, demo=demo)
    siap_id = {l["id"] for l in laporan if l["siap_direkomendasikan"]}
    for k in kegiatan:  # tanggal -> teks supaya bisa dikirim sebagai JSON
        if k.get("terakhir_diverifikasi"):
            k["terakhir_diverifikasi"] = k["terakhir_diverifikasi"].isoformat()
    return [k for k in kegiatan if k["id"] in siap_id], kegiatan, laporan


def buat_llm_default():
    from llm import buat_llm
    return buat_llm(config.PENYEDIA_AI)


def create_app(db_path=None, pembuat_llm=None, demo=None):
    """pembuat_llm: fungsi tanpa argumen yang mengembalikan llm(system, user) -> str.
    Dibuat saat permintaan pertama, jadi server tetap bisa menyala walau kunci API belum diisi."""
    demo = config.MODE_DEMO if demo is None else demo
    db = Database(db_path or config.DATABASE_PATH)
    siap, semua, laporan = muat_kegiatan(demo, config.MASA_BERLAKU_HARI)
    jarak = muat_jarak(config.DATA["jarak"]) if config.DATA["jarak"].exists() else None
    pembatas = PembatasLogin()
    pembuat_llm = pembuat_llm or buat_llm_default
    llm_cache = {}

    if config.JWT_SEMENTARA:
        log.warning("JWT_SECRET belum diatur di .env: token login hilang tiap server dinyalakan ulang.")
    log.info("Kegiatan siap direkomendasikan: %d dari %d (mode demo: %s)", len(siap), len(semua), demo)

    app = FastAPI(title="Pathora API", version="0.1.0",
                  description="Backend Pathora: akun pengguna, riwayat, dan asisten itinerary berbasis Claude.")
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    bearer = HTTPBearer(auto_error=False)

    def pengguna_aktif(cred: HTTPAuthorizationCredentials = Depends(bearer)):
        if cred is None:
            raise HTTPException(401, "Silakan login dulu.")
        pid = baca_token(cred.credentials, config.JWT_SECRET)
        p = db.pengguna_by_id(pid) if pid else None
        if not p:
            raise HTTPException(401, "Sesi tidak valid atau sudah habis. Silakan login lagi.")
        return p

    def ambil_llm():
        if "llm" not in llm_cache:
            try:
                asli = pembuat_llm()
            except RuntimeError as e:  # misalnya kunci API belum diisi: pakai jalur cadangan, coba lagi nanti
                log.error("Model bahasa tidak siap: %s", e)
                alasan = str(e)

                def mati(system, user):
                    raise RuntimeError(alasan)
                return mati

            def llm_tercatat(system, user):
                # asisten.py mengubah galat model jadi pesan ramah; di sini galat aslinya dicatat ke terminal
                try:
                    return asli(system, user)
                except Exception as e:
                    log.error("Panggilan model bahasa gagal: %s", e)
                    raise
            llm_cache["llm"] = llm_tercatat
        return llm_cache["llm"]

    # ---------- umum ----------
    @app.get("/", include_in_schema=False)
    def halaman_uji():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode_demo": demo, "penyedia_ai": config.PENYEDIA_AI,
                "kegiatan_siap": len(siap), "kegiatan_total": len(semua)}

    @app.get("/api/kegiatan")
    def daftar_kegiatan():
        return [{f: k.get(f) for f in KOLOM_PUBLIK} for k in siap]

    # ---------- auth ----------
    @app.post("/api/auth/signup", status_code=201)
    def signup(d: Daftar):
        p = db.buat_pengguna(d.nama, d.email, hash_password(d.password))
        if p is None:
            raise HTTPException(409, "Email sudah terdaftar. Silakan login.")
        return {"token": buat_token(p["id"], config.JWT_SECRET, config.TOKEN_BERLAKU_JAM), "pengguna": _publik(p)}

    @app.post("/api/auth/login")
    def login(d: Masuk, request: Request):
        email = d.email.strip().lower()
        kunci = f"{email}|{request.client.host if request.client else '-'}"
        if pembatas.diblokir(kunci):
            raise HTTPException(429, "Terlalu banyak percobaan login. Coba lagi 15 menit lagi.")
        p = db.pengguna_by_email(email)
        cocok = cek_password(d.password, p["password_hash"] if p else HASH_PALSU)
        if not p or not cocok:
            pembatas.catat_gagal(kunci)
            raise HTTPException(401, "Email atau password salah.")
        pembatas.reset(kunci)
        return {"token": buat_token(p["id"], config.JWT_SECRET, config.TOKEN_BERLAKU_JAM), "pengguna": _publik(p)}

    @app.get("/api/auth/me")
    def saya(p=Depends(pengguna_aktif)):
        return _publik(p)

    # ---------- asisten itinerary ----------
    @app.post("/api/rencana")
    def buat_rencana(d: PermintaanRencana, p=Depends(pengguna_aktif)):
        teks = d.teks.strip()
        if d.lanjutan_dari is not None:
            sebelumnya = db.ambil_permintaan(p["id"], d.lanjutan_dari)
            if not sebelumnya:
                raise HTTPException(404, "Permintaan sebelumnya tidak ditemukan.")
            teks = f"{sebelumnya['teks']}\n{teks}"
        try:
            hasil = jawab(teks, siap, ambil_llm(), jarak, semua, cadangan_aturan=True)
        except RuntimeError as e:  # misalnya kunci API belum diisi
            log.error("Model bahasa tidak siap: %s", e)
            llm_cache.clear()
            hasil = {"tipe": "galat", "pesan": "Maaf, asisten sedang tidak tersedia. Coba lagi sebentar lagi."}
        pid = db.simpan_permintaan(p["id"], teks, hasil)
        return {"id": pid, **hasil}

    @app.get("/api/rencana")
    def riwayat(p=Depends(pengguna_aktif)):
        return db.daftar_permintaan(p["id"])

    @app.get("/api/rencana/{rid}")
    def detail(rid: int, p=Depends(pengguna_aktif)):
        r = db.ambil_permintaan(p["id"], rid)
        if not r:
            raise HTTPException(404, "Tidak ditemukan.")
        return r

    @app.delete("/api/rencana/{rid}", status_code=204)
    def hapus(rid: int, p=Depends(pengguna_aktif)):
        if not db.hapus_permintaan(p["id"], rid):
            raise HTTPException(404, "Tidak ditemukan.")

    app.state.db = db
    return app


logging.basicConfig(level=logging.INFO)
app = create_app()
