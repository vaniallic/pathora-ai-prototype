"""Penyusun itinerary berbasis aturan. Tidak memakai model bahasa.

Yang boleh masuk itinerary hanya kegiatan yang sudah lolos pemeriksaan di load_data.py
(file out/kegiatan_siap.json). Semua angka (harga, durasi) diambil dari data, tidak dikarang.

Pakai (contoh):
    python3 planner.py out/kegiatan_siap.json '{"durasi_hari": 2, "tema": ["alam"]}'
"""
import json
import sys
from datetime import date, timedelta

HARI = ["senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu"]

# Aturan awal. Angka ini asumsi untuk diuji dan diubah bersama tim, bukan fakta.
ATURAN = {
    "maks_kegiatan_per_hari": 2,
    "maks_jam_kegiatan_per_hari": 8.0,
    "maks_menit_tempuh_per_hari": 120,
}

KESULITAN_BOLEH = {
    "santai": {"mudah"},
    "sedang": {"mudah", "sedang"},
    "aktif": {"mudah", "sedang", "berat"},
}


def menit_tempuh(desa_a, desa_b, jarak):
    """Menit tempuh antar dua desa. None kalau belum ada datanya."""
    if desa_a == desa_b:
        return 0
    return jarak.get((desa_a, desa_b), jarak.get((desa_b, desa_a)))


def susun(kegiatan_siap, prefs, jarak=None, aturan=None):
    jarak = jarak or {}
    a = {**ATURAN, **(aturan or {})}

    hari_n = int(prefs.get("durasi_hari") or 1)
    orang = int(prefs.get("jumlah_orang") or 1)
    tema = {t.lower() for t in (prefs.get("tema") or [])}
    budget = prefs.get("budget_per_hari")  # per orang per hari, dalam Rp
    mulai = prefs.get("tanggal_mulai")  # "YYYY-MM-DD" atau None
    batas = KESULITAN_BOLEH.get((prefs.get("tingkat_aktivitas") or "").lower())

    pool = []
    for k in kegiatan_siap:
        if batas and k["tingkat_kesulitan"] not in batas:
            continue
        if tema and k["tema"] not in tema:
            continue
        pool.append(k)

    catatan = []
    if not pool:
        catatan.append("Belum ada kegiatan terverifikasi yang cocok dengan permintaan ini.")
        return {"hari": [], "total_biaya_per_orang": 0, "catatan": catatan}

    terpakai = set()
    hari_hasil = []
    total = 0
    for i in range(hari_n):
        nama_hari = None
        if mulai:
            nama_hari = HARI[(date.fromisoformat(mulai) + timedelta(days=i)).weekday()]

        kandidat = [k for k in pool
                    if k["id"] not in terpakai
                    and (nama_hari is None or nama_hari not in k["hari_tutup"])]
        kandidat.sort(key=lambda k: (k["desa"], k["id"]))  # kegiatan satu desa berdekatan

        pilihan, jam, tempuh, biaya = [], 0.0, 0, 0
        for k in kandidat:
            if len(pilihan) >= a["maks_kegiatan_per_hari"]:
                break
            if jam + k["durasi_jam"] > a["maks_jam_kegiatan_per_hari"]:
                # kegiatan sehari penuh (lebih dari batas) boleh jadi satu-satunya kegiatan hari itu
                if pilihan or k["durasi_jam"] <= a["maks_jam_kegiatan_per_hari"]:
                    continue
            if budget is not None and biaya + k["harga_per_orang"] > budget:
                continue
            if k["kuota"] < orang:
                continue
            t = 0
            if pilihan:
                t = menit_tempuh(pilihan[-1]["desa"], k["desa"], jarak)
                if t is None:
                    continue  # waktu tempuh belum ada datanya: jangan digabung di hari yang sama
                if tempuh + t > a["maks_menit_tempuh_per_hari"]:
                    continue
            pilihan.append({**k, "_tempuh": t})
            jam += k["durasi_jam"]
            tempuh += t
            biaya += k["harga_per_orang"]
            if k["durasi_jam"] > a["maks_jam_kegiatan_per_hari"]:
                break  # kegiatan sehari penuh: tidak ditambah kegiatan lain

        if not pilihan:
            catatan.append(f"Hari {i + 1}: tidak ada kegiatan terverifikasi yang cocok.")
        for k in pilihan:
            terpakai.add(k["id"])
        total += biaya
        hari_hasil.append({
            "hari": i + 1,
            "kegiatan": [{
                "id": k["id"], "nama": k["nama"], "desa": k["desa"],
                "harga_per_orang": k["harga_per_orang"], "durasi_jam": k["durasi_jam"],
                "tempuh_dari_sebelumnya_menit": k["_tempuh"],
                **({"demo": True} if k.get("demo") else {}),
            } for k in pilihan],
        })
    hasil = {"hari": hari_hasil, "total_biaya_per_orang": total, "catatan": catatan}
    if any(k.get("demo") for h in hari_hasil for k in h["kegiatan"]):
        hasil["demo"] = True
    return hasil


if __name__ == "__main__":
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    prefs = json.loads(sys.argv[2])
    print(json.dumps(susun(data, prefs), ensure_ascii=False, indent=2))
