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
KEBUTUHAN = {"kursi_roda", "anak_kecil", "lansia", "alergi_makanan", "vegetarian", "lainnya"}
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


def validasi_prefs(d, hari_ini=None):
    """Cek bentuk dan nilai preferensi. Melempar ValueError kalau tidak valid.
    hari_ini (date) dipakai untuk menolak tanggal mulai yang sudah lewat."""
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
        tgl = date.fromisoformat(mulai)  # ValueError kalau format salah
        if hari_ini is not None and tgl < hari_ini:
            raise ValueError(f"tanggal_mulai {mulai} sudah lewat (hari ini {hari_ini.isoformat()}); "
                             "isi null kalau tanggalnya tidak jelas")
    lokasi = d.get("lokasi_diminta") or []
    if not isinstance(lokasi, list) or not all(isinstance(x, str) for x in lokasi):
        raise ValueError("lokasi_diminta harus daftar teks")
    kebutuhan = d.get("kebutuhan_khusus") or []
    if not isinstance(kebutuhan, list) or any(x not in KEBUTUHAN for x in kebutuhan):
        raise ValueError(f"kebutuhan_khusus harus dari {sorted(KEBUTUHAN)}, dapat {kebutuhan!r}")
    minat = d.get("minat_khusus") or []
    if not isinstance(minat, list) or not all(isinstance(x, str) and len(x) <= 40 for x in minat) or len(minat) > 8:
        raise ValueError("minat_khusus harus daftar teks pendek (maks 8)")
    luar = d.get("di_luar_cakupan", False)
    if not isinstance(luar, bool):
        raise ValueError("di_luar_cakupan harus true atau false")
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
        "lokasi_diminta": lokasi,
        "kebutuhan_khusus": kebutuhan,
        "minat_khusus": [x.strip().lower() for x in minat if x.strip()],
        "di_luar_cakupan": luar,
        "catatan": str(d.get("catatan") or ""),
        "perlu_tanya": tanya,
    }


def ekstrak_preferensi(teks, llm, maks_coba=2, system_prompt=None, hari_ini=None):
    system = system_prompt or muat_system_prompt()
    hari_ini = hari_ini or date.today()
    dasar = f"Tanggal hari ini: {hari_ini.isoformat()}\n\nPermintaan wisatawan: {teks}"
    pesan = dasar
    terakhir = None
    for _ in range(maks_coba):
        mentah = llm(system, pesan)
        try:
            return validasi_prefs(_json_dari(mentah), hari_ini)
        except (ValueError, json.JSONDecodeError) as e:
            terakhir = e
            pesan = f"{dasar}\n\n(Balasan sebelumnya tidak valid: {e}. Balas JSON sesuai skema saja.)"
    raise GagalEkstraksi(f"Gagal memahami permintaan setelah {maks_coba} percobaan: {terakhir}")
