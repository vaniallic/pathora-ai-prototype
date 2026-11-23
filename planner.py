"""Penyusun itinerary berbasis aturan. Tidak memakai model bahasa.

Yang boleh masuk itinerary hanya kegiatan yang sudah lolos pemeriksaan di load_data.py
(file out/kegiatan_siap.json). Semua angka (harga, durasi) diambil dari data, tidak dikarang.

Pakai (contoh):
    python3 planner.py out/kegiatan_siap.json '{"durasi_hari": 2, "tema": ["alam"]}'
"""
import json
import re
import sys
from datetime import date, timedelta

HARI = ["senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu"]

# Aturan awal. Angka ini asumsi untuk diuji dan diubah bersama tim, bukan fakta.
ATURAN = {
    "maks_kegiatan_per_hari": 2,
    "maks_jam_kegiatan_per_hari": 8.0,
    "maks_menit_tempuh_per_hari": 120,
    "maks_jam_santai": 6.0,  # wisatawan santai atau lansia: kegiatan lebih lama dari ini tidak ditawarkan
}

# Daerah yang datanya sudah dicakup Pathora saat ini. Tambah saat area baru masuk.
AREA_TERCAKUP = {"karangasem", "bali timur"}

# HEURISTIK (bukan data resmi): kata di kolom 'Cocok untuk' yang menandakan kegiatan kurang pas
# untuk anak kecil atau lansia. Tujuannya menyaring dengan hati-hati, bukan menjamin keamanan.
TANDA_TIDAK_UNTUK_ANAK = ("dewasa", "remaja", "minimal", "fit", "bugar")
TANDA_TIDAK_UNTUK_LANSIA = ("kurang cocok untuk lansia", "fit", "bugar", "kuat naik")

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


def _lokasi_tercakup(lokasi, kegiatan):
    l = lokasi.lower().strip()
    if not l:
        return True
    if any(a in l or l in a for a in AREA_TERCAKUP):
        return True
    for k in kegiatan:
        desa = k["desa"].lower()
        if l in desa:
            return True
        nama = desa.split("(")[0].strip()
        if nama and nama in l:
            return True
    return False


def _tema_set(k):
    """Tema kegiatan sebagai himpunan. 'Alam, Petualangan' atau 'Budaya & Alam' dibaca sebagai dua tema."""
    return {t.strip() for t in re.split(r"[,/&]|\bdan\b", (k.get("tema") or "").lower()) if t.strip()}


def _teks_cari(k):
    return " ".join((k.get(f) or "") for f in ("nama", "catatan", "fasilitas")).lower()


# Kata yang terlalu umum untuk dipakai sebagai minat khusus (itu urusan tema atau selera, bukan kata kunci kegiatan).
KATA_UMUM = {"lokal", "tersembunyi", "unik", "seru", "populer", "jarang", "terkenal", "indah", "bagus", "menarik",
             "alam", "budaya", "spiritual", "satwa", "petualangan", "kegiatan", "wisata", "liburan", "santai"}


def _minat_bersih(minat):
    """Buang minat yang terlalu panjang atau terlalu umum, supaya tidak muncul peringatan yang tidak berarti."""
    hasil = []
    for m in minat or []:
        m = m.lower().strip()
        kata = m.split()
        if not m or len(kata) > 2 or any(w in KATA_UMUM for w in kata):
            continue
        hasil.append(m)
    return hasil


def _skor_minat(k, minat):
    t = _teks_cari(k)
    return sum(1 for m in minat if m in t)


def _cocok_untuk(k):
    return (k.get("cocok_untuk") or "").lower()


def _kosong(catatan):
    return {"hari": [], "total_biaya_per_orang": 0, "catatan": catatan}


def susun(kegiatan_siap, prefs, jarak=None, aturan=None):
    jarak = jarak or {}
    a = {**ATURAN, **(aturan or {})}

    hari_n = int(prefs.get("durasi_hari") or 1)
    orang = int(prefs.get("jumlah_orang") or 1)
    tema = {t.lower() for t in (prefs.get("tema") or [])}
    budget = prefs.get("budget_per_hari")  # per orang per hari, dalam Rp
    mulai = prefs.get("tanggal_mulai")  # "YYYY-MM-DD" atau None
    batas = KESULITAN_BOLEH.get((prefs.get("tingkat_aktivitas") or "").lower())

    catatan = []
    for lok in prefs.get("lokasi_diminta") or []:
        if not _lokasi_tercakup(lok, kegiatan_siap):
            catatan.append(f"Belum ada kegiatan di {lok}. Rencana ini memakai kegiatan di wilayah lain yang tersedia.")
    tema_cari = set(tema)
    for t in sorted(tema):
        if any(t in _tema_set(k) for k in kegiatan_siap):
            continue
        if t == "petualangan":  # belum ada yang diberi tema ini: pakai kegiatan alam sebagai pengganti terdekat
            tema_cari = (tema_cari - {t}) | {"alam"}
            catatan.append("Belum ada kegiatan yang diberi tema petualangan. Kami menawarkan kegiatan alam "
                           "sebagai yang paling dekat.")
        else:
            catatan.append(f"Belum ada kegiatan bertema {t}.")
    minat = _minat_bersih(prefs.get("minat_khusus"))
    belum = [m for m in minat if not any(m in _teks_cari(k) for k in kegiatan_siap)]
    if belum:
        catatan.append("Belum ada kegiatan yang berkaitan dengan: " + ", ".join(belum) + ".")
    kebutuhan = set(prefs.get("kebutuhan_khusus") or [])
    if "kursi_roda" in kebutuhan:
        catatan.append("Kami belum punya data aksesibilitas kursi roda untuk kegiatan mana pun, jadi belum bisa "
                       "merekomendasikan dengan aman. Tanyakan langsung ke host.")
        return _kosong(catatan)
    if "lainnya" in kebutuhan:
        catatan.append("Kebutuhan khususmu belum ada di data kami. Tanyakan langsung ke host sebelum memesan.")
    if kebutuhan & {"alergi_makanan", "vegetarian"}:
        catatan.append("Data makanan dan menu di tiap kegiatan belum ada. Tanyakan ke host soal makanan, "
                       "alergi, dan menu vegetarian sebelum memesan.")
    if kebutuhan & {"anak_kecil", "lansia"}:
        catatan.append("Data kecocokan untuk anak kecil dan lansia belum lengkap. Kegiatan yang tampak kurang "
                       "cocok sudah disaring, tapi tetap konfirmasi ke host.")

    pool = []
    for k in kegiatan_siap:
        if "anak_kecil" in kebutuhan and any(w in _cocok_untuk(k) for w in TANDA_TIDAK_UNTUK_ANAK):
            continue
        if "lansia" in kebutuhan and any(w in _cocok_untuk(k) for w in TANDA_TIDAK_UNTUK_LANSIA):
            continue
        if batas and k["tingkat_kesulitan"] not in batas:
            continue
        if (prefs.get("tingkat_aktivitas") == "santai" or "lansia" in kebutuhan) \
                and k["durasi_jam"] > a["maks_jam_santai"]:
            continue
        if tema_cari and not (_tema_set(k) & tema_cari):
            continue
        pool.append(k)

    if not pool:
        catatan.append("Belum ada kegiatan yang cocok dengan permintaan ini.")
        return _kosong(catatan)
    if orang > 1 and all(k["kuota"] < orang for k in pool):
        catatan.append(f"Belum ada kegiatan dengan kuota cukup untuk {orang} orang.")
        return _kosong(catatan)

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
        # yang sesuai minat khusus lebih dulu; selain itu kegiatan satu desa berdekatan
        kandidat.sort(key=lambda k: (-_skor_minat(k, minat), k["desa"], k["id"]))

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
            catatan.append(f"Hari {i + 1}: belum ada kegiatan yang cocok.")
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
    for m in minat:
        cocok = [k for k in kegiatan_siap if m in _teks_cari(k)]
        if cocok and not any(k["id"] in terpakai for k in cocok):
            catatan.append(f"Ada kegiatan yang berkaitan dengan '{m}', tapi tidak cocok dengan tingkat aktivitas, "
                           "kebutuhan, atau tema yang kamu pilih, jadi tidak ditawarkan.")
    hasil = {"hari": hari_hasil, "total_biaya_per_orang": total, "catatan": catatan}
    if any(k.get("demo") for h in hari_hasil for k in h["kegiatan"]):
        hasil["demo"] = True
    return hasil


if __name__ == "__main__":
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    prefs = json.loads(sys.argv[2])
    print(json.dumps(susun(data, prefs), ensure_ascii=False, indent=2))
