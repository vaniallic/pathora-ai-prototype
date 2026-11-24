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


# ---------- Cadangan tanpa model bahasa ----------
# Dipakai hanya kalau model bahasa sedang tidak bisa dihubungi (misalnya server Gemini penuh).
# Hasilnya lebih kasar dari model, tapi tetap melewati validasi yang sama.
ANGKA_KATA = {"satu": 1, "se": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6, "tujuh": 7,
              "delapan": 8, "sembilan": 9, "sepuluh": 10}
KATA_TEMA = {
    "alam": ("alam", "air terjun", "pantai", "gunung", "bukit", "sawah", "pemandangan", "trekking", "hutan", "danau"),
    "budaya": ("budaya", "tradisi", "tradisional", "adat", "tenun", "garam", "arak", "kerajinan", "desa adat", "lokal"),
    "spiritual": ("spiritual", "pura", "meditasi", "yoga", "upacara", "melukat"),
    "satwa": ("satwa", "hewan", "binatang", "burung", "penyu", "lumba"),
    "petualangan": ("petualangan", "camping", "kemah", "menantang", "ekstrem", "seru"),
}
KATA_SANTAI = ("santai", "jangan yang berat", "nggak mau capek", "tidak mau capek", "gak mau capek",
               "gampang capek", "jangan capek", "ringan", "nggak berat", "tidak berat")
KATA_AKTIF = ("aktif", "menantang", "berat juga", "kuat jalan", "fit")
KATA_LUAR = ("hotel", "tiket pesawat", "penginapan", "restoran", "sewa mobil", "villa")


def _ada(teks, kata):
    return any(re.search(r"\b" + re.escape(k) + r"\b", teks) for k in kata)


def ekstrak_aturan(teks, hari_ini=None):
    """Menebak preferensi dari kata kunci, tanpa model bahasa. Selalu lolos validasi_prefs."""
    t = " " + (teks or "").lower() + " "
    durasi = None
    m = re.search(r"(\d{1,2})\s*(hari|malam)", t)
    if m:
        durasi = int(m.group(1)) + (1 if m.group(2) == "malam" else 0)
    else:
        m = re.search(r"\b(satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh)\s+(hari|malam)", t)
        if m:
            durasi = ANGKA_KATA[m.group(1)] + (1 if m.group(2) == "malam" else 0)
        elif _ada(t, ("seminggu", "satu minggu", "1 minggu")):
            durasi = 7
        elif _ada(t, ("sehari", "seharian")):
            durasi = 1
        elif _ada(t, ("weekend", "akhir pekan")):
            durasi = 2
    if durasi is not None:
        durasi = max(1, min(durasi, 14))

    orang = None
    m = re.search(r"(\d{1,2})\s*orang", t)
    if m:
        orang = max(1, min(int(m.group(1)), 50))
    elif _ada(t, ("berdua", "sama pacar", "sama pacarku", "pasangan", "suami", "istri")):
        orang = 2
    elif _ada(t, ("bertiga",)):
        orang = 3
    elif _ada(t, ("berempat",)):
        orang = 4
    elif _ada(t, ("sendiri", "sendirian", "solo")):
        orang = 1

    tema = [nama for nama, kata in KATA_TEMA.items() if _ada(t, kata)]
    aktivitas = "santai" if _ada(t, KATA_SANTAI) else ("aktif" if _ada(t, KATA_AKTIF) else None)
    kebutuhan = []
    if _ada(t, ("anak", "anak kecil", "anak-anak", "balita", "bayi")):
        kebutuhan.append("anak_kecil")
    if _ada(t, ("lansia", "orang tua", "kakek", "nenek", "orangtua")):
        kebutuhan.append("lansia")
    if _ada(t, ("kursi roda",)):
        kebutuhan.append("kursi_roda")
    if _ada(t, ("vegetarian", "vegan")):
        kebutuhan.append("vegetarian")
    if _ada(t, ("alergi",)):
        kebutuhan.append("alergi_makanan")
    luar = _ada(t, KATA_LUAR) and not tema and durasi is None

    return validasi_prefs({
        "durasi_hari": durasi, "jumlah_orang": orang, "tema": tema, "tingkat_aktivitas": aktivitas,
        "budget_per_hari": None, "tanggal_mulai": None, "lokasi_diminta": [], "kebutuhan_khusus": kebutuhan,
        "minat_khusus": [], "di_luar_cakupan": luar, "catatan": "dipahami tanpa model bahasa",
        "perlu_tanya": [] if durasi else ["Berapa hari kamu berencana di Bali?"],
    }, hari_ini)
