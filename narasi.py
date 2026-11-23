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


def rupiah(n):
    return "Rp" + f"{int(n):,}".replace(",", ".")


def narasi_cadangan(rencana):
    """Penjelasan sederhana dari data, tanpa model bahasa."""
    if not rencana["hari"] or not any(h["kegiatan"] for h in rencana["hari"]):
        return ("Maaf, belum ada kegiatan terverifikasi yang cocok dengan permintaanmu. "
                "Coba ubah tema atau durasinya, atau kabari kami lagi nanti.")
    baris = []
    for h in rencana["hari"]:
        if not h["kegiatan"]:
            baris.append(f"Hari {h['hari']}: belum ada kegiatan terverifikasi yang cocok.")
            continue
        for k in h["kegiatan"]:
            baris.append(f"Hari {h['hari']}: {k['nama']} di {k['desa']} "
                         f"({k['durasi_jam']} jam, {rupiah(k['harga_per_orang'])} per orang).")
    baris.append(f"Perkiraan total: {rupiah(rencana['total_biaya_per_orang'])} per orang.")
    baris.append("Ini baru permintaan. Host akan mengonfirmasi ketersediaannya.")
    if rencana.get("demo"):
        baris.append(LABEL_DEMO)
    return "\n".join(baris)


def periksa_narasi(teks, rencana, semua_kegiatan):
    """Daftar masalah di penjelasan model. Kosong berarti lolos."""
    masalah = []
    harga_boleh = {rencana["total_biaya_per_orang"]}
    id_rencana = set()
    for h in rencana["hari"]:
        for k in h["kegiatan"]:
            harga_boleh.add(k["harga_per_orang"])
            id_rencana.add(k["id"])
    for m in re.finditer(r"Rp\s?([\d.,]+)", teks):
        angka = re.sub(r"[.,]", "", m.group(1))
        if angka and int(angka) not in harga_boleh:
            masalah.append(f"harga {m.group(0)} tidak ada di rencana")
    bawah = teks.lower()
    for k in semua_kegiatan:
        if k["id"] not in id_rencana and k["nama"].lower() in bawah:
            masalah.append(f"menyebut kegiatan di luar rencana: {k['nama']}")
    return masalah


def tulis_narasi(rencana, semua_kegiatan, llm, maks_coba=2, system_prompt=None):
    if not any(h["kegiatan"] for h in rencana["hari"]):
        return narasi_cadangan(rencana)  # tidak ada yang perlu dijelaskan model
    system = system_prompt or muat_system_prompt()
    isi = json.dumps(rencana, ensure_ascii=False)
    for _ in range(maks_coba):
        teks = llm(system, isi)
        if not periksa_narasi(teks, rencana, semua_kegiatan):
            return f"{teks}\n\n{LABEL_DEMO}" if rencana.get("demo") else teks
    return narasi_cadangan(rencana)
