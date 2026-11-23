"""Tahap 4: menjelaskan hasil planner. Model boleh menulis, tapi kode memeriksa hasilnya.

Kalau penjelasan dari model memuat harga yang tidak ada di rencana, atau menyebut kegiatan
yang tidak ada di rencana, penjelasan ditolak. Setelah beberapa kali gagal, dipakai teks
cadangan yang disusun langsung dari data (tanpa model).
"""
import json
import re
from pathlib import Path

PROMPT_MD = Path(__file__).parent / "prompts" / "narasi_itinerary.md"


def muat_system_prompt(path=PROMPT_MD):
    teks = Path(path).read_text(encoding="utf-8")
    m = re.search(r"## System prompt\s+```\n(.*?)```", teks, re.S)
    if not m:
        raise ValueError(f"System prompt tidak ditemukan di {path}")
    return m.group(1).strip()


LABEL_DEMO = "Versi prototype: harga dan ketersediaan masih contoh dan akan dikonfirmasi host."


def jam(x):
    """1.5 -> '1,5', 2 -> '2' (format Indonesia)."""
    return str(x).replace(".", ",")


def rupiah(n):
    return "Rp" + f"{int(n):,}".replace(",", ".")


def _blok_catatan(rencana):
    if not rencana.get("catatan"):
        return ""
    return "Yang perlu diketahui:\n" + "\n".join(f"- {c}" for c in rencana["catatan"])


def _akhiri(teks, rencana):
    """Tambahkan catatan dari sistem dan label prototype. Dilakukan kode, bukan model."""
    bagian = [teks.strip()]
    if _blok_catatan(rencana):
        bagian.append(_blok_catatan(rencana))
    if rencana.get("demo"):
        bagian.append(LABEL_DEMO)
    return "\n\n".join(bagian)


def narasi_cadangan(rencana):
    """Penjelasan sederhana dari data, tanpa model bahasa."""
    ada = [h for h in rencana["hari"] if h["kegiatan"]]
    if not ada:
        kepala = "Maaf, belum ada kegiatan yang cocok dengan permintaanmu."
        if not rencana.get("catatan"):
            kepala += " Coba ubah tema atau durasinya, atau kabari kami lagi nanti."
        return _akhiri(kepala, rencana)
    baris = []
    for h in ada:
        for k in h["kegiatan"]:
            baris.append(f"Hari {h['hari']}: {k['nama']} di {k['desa']} "
                         f"({jam(k['durasi_jam'])} jam, {rupiah(k['harga_per_orang'])} per orang).")
    baris.append(f"Perkiraan total: {rupiah(rencana['total_biaya_per_orang'])} per orang.")
    baris.append("Ini baru permintaan. Host akan mengonfirmasi ketersediaannya.")
    return _akhiri("\n".join(baris), rencana)


def periksa_narasi(teks, rencana, semua_kegiatan):
    """Daftar masalah di penjelasan model. Kosong berarti lolos."""
    masalah = []
    harga_boleh = {rencana["total_biaya_per_orang"]}
    id_rencana = set()
    for h in rencana["hari"]:
        for k in h["kegiatan"]:
            harga_boleh.add(k["harga_per_orang"])
            id_rencana.add(k["id"])
    for m in re.finditer(r"(?:Rp\s?)?(\d{1,3}(?:[.,]\d{3})+|\d{4,})", teks):
        angka = int(re.sub(r"[.,]", "", m.group(1)))
        if 1900 <= angka <= 2100 and not m.group(0).startswith("Rp"):
            continue  # kemungkinan tahun
        if angka not in harga_boleh:
            masalah.append(f"angka {m.group(0)} tidak ada di rencana")
    bawah = teks.lower()
    for k in semua_kegiatan:
        if k["id"] not in id_rencana and k["nama"].lower() in bawah:
            masalah.append(f"menyebut kegiatan di luar rencana: {k['nama']}")
    return masalah


def tulis_narasi(rencana, semua_kegiatan, llm, maks_coba=2, system_prompt=None):
    if not any(h["kegiatan"] for h in rencana["hari"]):
        return narasi_cadangan(rencana)  # tidak ada yang perlu dijelaskan model
    system = system_prompt or muat_system_prompt()
    # Model hanya menerima hari yang berisi kegiatan. Catatan dan label ditambahkan oleh kode.
    untuk_model = {"hari": [{**h, "kegiatan": [{**k, "durasi_jam": jam(k["durasi_jam"])} for k in h["kegiatan"]]}
                            for h in rencana["hari"] if h["kegiatan"]],
                   "total_biaya_per_orang": rencana["total_biaya_per_orang"]}
    isi = json.dumps(untuk_model, ensure_ascii=False)
    for _ in range(maks_coba):
        teks = llm(system, isi)
        if not periksa_narasi(teks, rencana, semua_kegiatan):
            return _akhiri(teks, rencana)
    return narasi_cadangan(rencana)
