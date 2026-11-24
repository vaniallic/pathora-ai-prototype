"""Pengaturan backend, dibaca dari variabel lingkungan atau berkas .env di folder backend/.

Kunci rahasia (ANTHROPIC_API_KEY, JWT_SECRET) hanya boleh ada di .env server, tidak pernah di repo.
"""
import os
import secrets
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent  # folder repo
BACKEND = Path(__file__).resolve().parent


def _muat_env(path):
    """Pembaca .env sederhana (KUNCI=nilai). Variabel yang sudah diatur di sistem tidak ditimpa."""
    if not path.exists():
        return
    for baris in path.read_text(encoding="utf-8").splitlines():
        baris = baris.strip()
        if not baris or baris.startswith("#") or "=" not in baris:
            continue
        k, v = baris.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_muat_env(BACKEND / ".env")


def _bool(nama, default):
    return os.environ.get(nama, str(default)).strip().lower() in {"1", "true", "ya", "yes"}


PENYEDIA_AI = os.environ.get("PENYEDIA_AI", "gemini")  # gemini | anthropic
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH") or BACKEND / "pathora.db")
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = AKAR / DATABASE_PATH
MODE_DEMO = _bool("PATHORA_DEMO", True)  # data belum terverifikasi: pakai isian demo + label
MASA_BERLAKU_HARI = int(os.environ["MASA_BERLAKU_HARI"]) if os.environ.get("MASA_BERLAKU_HARI") else None
CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS", "https://pathoraweb.netlify.app,http://localhost:5173,http://localhost:8000").split(",") if o.strip()]

# Kuota pertanyaan AI per hari (hari dihitung WIB). Plus tetap diberi batas tinggi supaya tidak disalahgunakan.
KUOTA_HARIAN = {"gratis": int(os.environ.get("KUOTA_GRATIS", "5")), "plus": int(os.environ.get("KUOTA_PLUS", "200"))}
# Front-end menunggu maksimal 8 detik. Backend harus sudah menjawab sebelum itu (pakai cadangan kalau model lambat).
AI_BATAS_DETIK = float(os.environ.get("AI_BATAS_DETIK", "7"))
# Batas laju per alamat IP, untuk mencegah spam lintas akun.
BATAS_RENCANA_PER_MENIT = int(os.environ.get("BATAS_RENCANA_PER_MENIT", "20"))
BATAS_DAFTAR_PER_JAM = int(os.environ.get("BATAS_DAFTAR_PER_JAM", "10"))
TOKEN_BERLAKU_JAM = int(os.environ.get("TOKEN_BERLAKU_JAM", "24"))

JWT_SECRET = os.environ.get("JWT_SECRET")
JWT_SEMENTARA = not JWT_SECRET
if JWT_SEMENTARA:
    # Tanpa JWT_SECRET, semua pengguna harus login ulang tiap server dinyalakan ulang.
    JWT_SECRET = secrets.token_urlsafe(48)

DATA = {
    "kegiatan": AKAR / "data" / "Kegiatan.csv",
    "host": AKAR / "data" / "Host.csv",
    "isian_demo": AKAR / "data" / "isian_demo.csv",
    "jarak": AKAR / "data" / "jarak_desa.csv",  # opsional, belum ada
}
