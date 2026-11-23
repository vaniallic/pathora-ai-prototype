"""Tahap 2: mengubah kalimat bebas wisatawan menjadi preferensi terstruktur, lewat model bahasa.

Model hanya menerjemahkan. Hasilnya SELALU divalidasi oleh kode sebelum dipakai planner.
`llm` adalah fungsi biasa: llm(system: str, user: str) -> str (lihat llm.py).
"""
import json
import re
from datetime import date
from pathlib import Path

TEMA = {"alam", "budaya", "satwa", "spiritual", "petualangan"}
AKTIVITAS = {"santai", "sedang", "aktif"}
PROMPT_MD = Path(__file__).parent / "prompts" / "ekstraksi_permintaan.md"


class GagalEkstraksi(Exception):
    pass


def muat_system_prompt(path=PROMPT_MD):
    teks = Path(path).read_text(encoding="utf-8")
    m = re.search(r"## System prompt\s+```\n(.*?)```", teks, re.S)
    if not m:
        raise ValueError(f"System prompt tidak ditemukan di {path}")
    return m.group(1).strip()


def _json_dari(teks):
    t = teks.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return json.loads(t)


def _int_opsional(d, nama, lo, hi):
    v = d.get(nama)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValueError(f"{nama} harus bilangan bulat {lo}..{hi}, dapat {v!r}")
    return v


def validasi_prefs(d):
    """Cek bentuk dan nilai preferensi. Melempar ValueError kalau tidak valid."""
    if not isinstance(d, dict):
        raise ValueError("hasil ekstraksi bukan objek JSON")
    tema = d.get("tema") or []
    if not isinstance(tema, list) or any(t not in TEMA for t in tema):
        raise ValueError(f"tema harus dari {sorted(TEMA)}, dapat {tema!r}")
    aktivitas = d.get("tingkat_aktivitas")
    if aktivitas is not None and aktivitas not in AKTIVITAS:
        raise ValueError(f"tingkat_aktivitas harus dari {sorted(AKTIVITAS)}, dapat {aktivitas!r}")
    mulai = d.get("tanggal_mulai")
    if mulai is not None:
        date.fromisoformat(mulai)  # ValueError kalau format salah
    tanya = d.get("perlu_tanya") or []
    if not isinstance(tanya, list) or not all(isinstance(x, str) for x in tanya):
        raise ValueError("perlu_tanya harus daftar teks")
    return {
        "durasi_hari": _int_opsional(d, "durasi_hari", 1, 14),
        "jumlah_orang": _int_opsional(d, "jumlah_orang", 1, 50),
        "tema": tema,
        "tingkat_aktivitas": aktivitas,
        "budget_per_hari": _int_opsional(d, "budget_per_hari", 0, 10**9),
        "tanggal_mulai": mulai,
        "catatan": str(d.get("catatan") or ""),
        "perlu_tanya": tanya,
    }


def ekstrak_preferensi(teks, llm, maks_coba=2, system_prompt=None):
    system = system_prompt or muat_system_prompt()
    pesan = teks
    terakhir = None
    for _ in range(maks_coba):
        mentah = llm(system, pesan)
        try:
            return validasi_prefs(_json_dari(mentah))
        except (ValueError, json.JSONDecodeError) as e:
            terakhir = e
            pesan = f"{teks}\n\n(Balasan sebelumnya tidak valid: {e}. Balas JSON sesuai skema saja.)"
    raise GagalEkstraksi(f"Gagal memahami permintaan setelah {maks_coba} percobaan: {terakhir}")
