"""Menjalankan daftar permintaan uji (data/contoh_uji.csv) lewat asisten, lalu menulis laporan.

Pakai (perlu GEMINI_API_KEY):
    python3 uji_batch.py --data out_demo/kegiatan_siap.json --semua out_demo/kegiatan.json

Hasil: out_uji/laporan_uji.md dan out_uji/laporan_uji.csv. Jeda antar permintaan supaya
tidak kena batas laju free tier. Cek otomatis hanya memeriksa hal yang bisa dihitung;
kolom 'Yang diperiksa manual' tetap harus kamu baca sendiri.
"""
import argparse
import csv
import json
import time
from pathlib import Path

from datetime import date

from asisten import jawab, muat_jarak
from narasi import LABEL_DEMO, narasi_cadangan


def periksa_otomatis(kasus, hasil, semua):
    """Daftar temuan otomatis. Kosong berarti tidak ada masalah yang terdeteksi."""
    temuan = []
    ids = {k["id"] for k in semua}
    tipe = hasil["tipe"]
    harap = kasus["Harapan tipe"]
    kata = [w.strip().lower() for w in (kasus.get("Harapan peringatan") or "").split("|") if w.strip()]
    if kata and not any(w in hasil["pesan"].lower() for w in kata):
        temuan.append(f"jawaban harus menyebut salah satu dari: {', '.join(kata)}")
    for larangan in [w.strip().lower() for w in (kasus.get("Tidak boleh menyebut") or "").split("|") if w.strip()]:
        if larangan in hasil["pesan"].lower():
            temuan.append(f"jawaban tidak boleh menyebut: {larangan}")
    if tipe == "galat":
        temuan.append("GALAT: API bermasalah, kasus ini belum teruji")
        return temuan
    if harap == "tanya" and tipe != "tanya":
        temuan.append(f"harusnya bertanya balik, malah menghasilkan {tipe}")
    if harap == "rencana" and tipe == "tanya":
        temuan.append("harusnya menghasilkan rencana, malah bertanya balik")
    if tipe != "rencana":
        return temuan
    p, r = hasil["prefs"], hasil["rencana"]
    if p.get("tanggal_mulai") and date.fromisoformat(p["tanggal_mulai"]) < date.today():
        temuan.append(f"tanggal mulai {p['tanggal_mulai']} sudah lewat")
    if kasus["Harapan hari"] and p["durasi_hari"] != int(kasus["Harapan hari"]):
        temuan.append(f"durasi terbaca {p['durasi_hari']}, harapan {kasus['Harapan hari']}")
    if kasus["Harapan tema"]:
        harap_tema = set(kasus["Harapan tema"].split(","))
        if not harap_tema <= set(p["tema"]):
            temuan.append(f"tema terbaca {p['tema']}, harapan {sorted(harap_tema)}")
    for h in r["hari"]:
        for k in h["kegiatan"]:
            if k["id"] not in ids:
                temuan.append(f"kegiatan {k['id']} tidak ada di data")
    if p.get("jumlah_orang"):
        kuota = {k["id"]: k["kuota"] for k in semua}
        for h in r["hari"]:
            for k in h["kegiatan"]:
                if kuota.get(k["id"], 0) < p["jumlah_orang"]:
                    temuan.append(f"{k['id']} berkuota {kuota.get(k['id'])}, kurang dari {p['jumlah_orang']} orang")
    if p.get("budget_per_hari") is not None:
        for h in r["hari"]:
            if sum(k["harga_per_orang"] for k in h["kegiatan"]) > p["budget_per_hari"]:
                temuan.append(f"hari {h['hari']} melewati budget")
    if r.get("demo") and LABEL_DEMO not in hasil["pesan"]:
        temuan.append("label prototype hilang")
    if hasil["pesan"] == narasi_cadangan(r):
        temuan.append("info: memakai teks cadangan (penjelasan model ditolak atau tidak dipakai)")
    return temuan


def jalankan(kasus_list, kegiatan_siap, semua, llm, jarak=None, jeda=6.0, tidur=time.sleep):
    hasil_semua = []
    for i, kasus in enumerate(kasus_list):
        if i:
            tidur(jeda)
        h = jawab(kasus["Permintaan"], kegiatan_siap, llm, jarak, semua)
        if h["tipe"] == "galat":  # sekali lagi setelah menunggu (biasanya batas laju)
            tidur(max(jeda, 20))
            h = jawab(kasus["Permintaan"], kegiatan_siap, llm, jarak, semua)
        hasil_semua.append({"kasus": kasus, "hasil": h, "temuan": periksa_otomatis(kasus, h, semua)})
    return hasil_semua


def tulis_laporan(hasil_semua, folder):
    out = Path(folder)
    out.mkdir(exist_ok=True)
    masalah = [x for x in hasil_semua if any(not t.startswith("info:") for t in x["temuan"])]
    md = [f"# Laporan uji asisten Pathora", "",
          f"Kasus: {len(hasil_semua)}. Ada temuan otomatis: {len(masalah)}.", ""]
    for x in hasil_semua:
        k, h = x["kasus"], x["hasil"]
        md += [f"## {k['ID']}: {k['Permintaan']}", f"- Tipe: {h['tipe']}"]
        if h["tipe"] == "rencana":
            md.append(f"- Preferensi terbaca: `{json.dumps(h['prefs'], ensure_ascii=False)}`")
        md.append("- Temuan otomatis: " + ("; ".join(x["temuan"]) if x["temuan"] else "tidak ada"))
        if k["Yang diperiksa manual"]:
            md.append(f"- Periksa manual: {k['Yang diperiksa manual']}")
        md += ["", "```", h["pesan"], "```", ""]
    (out / "laporan_uji.md").write_text("\n".join(md), encoding="utf-8")
    with open(out / "laporan_uji.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Permintaan", "Tipe", "Temuan otomatis", "Periksa manual", "Jawaban"])
        for x in hasil_semua:
            k, h = x["kasus"], x["hasil"]
            w.writerow([k["ID"], k["Permintaan"], h["tipe"], " | ".join(x["temuan"]),
                        k["Yang diperiksa manual"], h["pesan"]])
    return len(masalah)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--semua", required=True)
    ap.add_argument("--uji", default="data/contoh_uji.csv")
    ap.add_argument("--jarak")
    ap.add_argument("--penyedia", default="gemini", choices=["gemini", "anthropic"])
    ap.add_argument("--jeda", type=float, default=6.0, help="detik antar permintaan")
    ap.add_argument("--out", default="out_uji")
    a = ap.parse_args()
    siap = json.load(open(a.data, encoding="utf-8"))
    semua = json.load(open(a.semua, encoding="utf-8"))
    with open(a.uji, newline="", encoding="utf-8-sig") as f:
        kasus = list(csv.DictReader(f))
    from llm import buat_llm
    hasil = jalankan(kasus, siap, semua, buat_llm(a.penyedia), muat_jarak(a.jarak) if a.jarak else None, a.jeda)
    n = tulis_laporan(hasil, a.out)
    print(f"Selesai: {len(hasil)} kasus, {n} punya temuan otomatis. Laporan: {a.out}/laporan_uji.md")


if __name__ == "__main__":
    main()
