"""Merangkai semuanya: permintaan wisatawan -> preferensi -> planner -> penjelasan.

Pakai (perlu API):
    python3 asisten.py "3 hari berdua, suka air terjun" --data out/kegiatan_siap.json --semua out/kegiatan.json

Pakai tanpa API (preferensi dimasukkan manual, penjelasan dari data):
    python3 asisten.py "" --data out/kegiatan_siap.json --prefs-json '{"durasi_hari": 2, "tema": ["alam"]}'
"""
import argparse
import csv
import json

from ekstrak import GagalEkstraksi, ekstrak_preferensi, validasi_prefs
from narasi import narasi_cadangan, tulis_narasi
from planner import susun


def muat_jarak(path):
    """CSV dengan kolom: Desa A, Desa B, Menit. Mengembalikan {(a, b): menit}."""
    jarak = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                jarak[(r["Desa A"].strip(), r["Desa B"].strip())] = int(r["Menit"])
            except (KeyError, ValueError):
                continue  # baris tidak lengkap dilewati
    return jarak


def jawab(teks, kegiatan_siap, llm, jarak=None, semua_kegiatan=None):
    try:
        prefs = ekstrak_preferensi(teks, llm)
    except GagalEkstraksi as e:
        if "durasi_hari" in str(e):
            return {"tipe": "tanya", "pesan": "Aku bisa menyusun rencana sampai 14 hari. "
                    "Berapa hari yang ingin kamu rencanakan?"}
        return {"tipe": "tanya", "pesan": "Maaf, aku belum bisa memahami permintaanmu. "
                "Coba ceritakan lagi: berapa hari kamu di sana dan kegiatan seperti apa yang kamu suka?"}
    except RuntimeError:
        return {"tipe": "galat", "pesan": "Maaf, asisten sedang sibuk. Coba lagi sebentar lagi."}
    if prefs["di_luar_cakupan"]:
        return {"tipe": "tanya", "pesan": "Maaf, Pathora fokus pada kegiatan alam dan budaya lokal di Bali, "
                "jadi aku belum bisa membantu soal itu (misalnya hotel, tiket, atau restoran). "
                "Kalau mau, ceritakan berapa hari kamu di Bali dan kegiatan seperti apa yang kamu suka."}
    if prefs["durasi_hari"] is None:
        pesan = " ".join(prefs["perlu_tanya"]) or "Berapa hari kamu berencana di sana?"
        return {"tipe": "tanya", "pesan": pesan}
    rencana = susun(kegiatan_siap, prefs, jarak)
    try:
        pesan = tulis_narasi(rencana, semua_kegiatan or kegiatan_siap, llm)
    except RuntimeError:
        pesan = narasi_cadangan(rencana)  # model bermasalah: pakai teks dari data
    return {"tipe": "rencana", "prefs": prefs, "rencana": rencana, "pesan": pesan}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("teks")
    ap.add_argument("--data", required=True, help="out/kegiatan_siap.json")
    ap.add_argument("--semua", help="out/kegiatan.json (untuk memeriksa nama kegiatan di penjelasan)")
    ap.add_argument("--jarak", help="CSV waktu tempuh antar desa")
    ap.add_argument("--prefs-json", help="lewati model: pakai preferensi ini")
    ap.add_argument("--penyedia", default="gemini", choices=["gemini", "anthropic"],
                    help="model bahasa yang dipakai (default gemini)")
    a = ap.parse_args()

    siap = json.load(open(a.data, encoding="utf-8"))
    semua = json.load(open(a.semua, encoding="utf-8")) if a.semua else siap
    jarak = muat_jarak(a.jarak) if a.jarak else None

    if a.prefs_json:
        prefs = validasi_prefs(json.loads(a.prefs_json))
        rencana = susun(siap, prefs, jarak)
        print(narasi_cadangan(rencana))
        return
    from llm import buat_llm
    hasil = jawab(a.teks, siap, buat_llm(a.penyedia), jarak, semua)
    print(hasil["pesan"])


if __name__ == "__main__":
    main()
