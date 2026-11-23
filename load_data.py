"""Baca CSV Pathora (tab Kegiatan dan Host), ubah jadi JSON rapi, dan cek kesiapan data.

Pakai:
    python3 load_data.py data/Kegiatan.csv data/Host.csv --out out
"""
import argparse
import csv
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

KEGIATAN_KOLOM = {
    "ID": "id",
    "Nama kegiatan": "nama",
    "Desa / Area": "desa",
    "Tema": "tema",
    "Status data": "status_data",
    "ID Host": "host_id",
    "Harga per orang (Rp)": "harga_per_orang",
    "Durasi (jam)": "durasi_jam",
    "Kuota per sesi": "kuota",
    "Hari tutup / tidak tersedia": "hari_tutup",
    "Cara booking": "cara_booking",
    "Titik kumpul": "titik_kumpul",
    "Cara ke sana": "cara_ke_sana",
    "Kondisi jalan": "kondisi_jalan",
    "Waktu tempuh dari bandara": "waktu_tempuh_bandara",
    "Tingkat kesulitan": "tingkat_kesulitan",
    "Cocok untuk": "cocok_untuk",
    "Fasilitas": "fasilitas",
    "Aturan budaya dan pakaian": "aturan_budaya",
    "Perlengkapan yang dibawa": "perlengkapan",
    "Risiko dan penanganan": "risiko",
    "Kebijakan cuaca buruk": "cuaca_buruk",
    "Link foto / video": "media",
    "Sumber data": "sumber",
    "Tanggal data diambil": "tanggal_data",
    "Catatan": "catatan",
    "Terakhir diverifikasi": "terakhir_diverifikasi",
}

HOST_KOLOM = {
    "ID Host": "host_id",
    "Nama pengelola": "nama",
    "Bentuk": "bentuk",
    "Desa / Area": "desa",
    "Kontak WhatsApp": "kontak_wa",
    "Status kontak": "status_kontak",
    "Setuju tampil di Pathora": "setuju_tampil",
    "Izin / legalitas": "izin",
    "Skema komisi yang diminta": "komisi",
    "Cara terima pembayaran": "pembayaran",
    "Kontak terakhir": "kontak_terakhir",
    "Catatan": "catatan",
}

# Tanpa ini, penyusun itinerary tidak bisa bekerja dengan benar.
WAJIB_PLANNER = ["harga_per_orang", "durasi_jam", "kuota", "tingkat_kesulitan"]
# Tanpa ini, kegiatan belum layak ditampilkan lengkap ke wisatawan.
WAJIB_TAMPIL = ["cara_booking", "titik_kumpul", "cara_ke_sana", "kondisi_jalan",
                "aturan_budaya", "risiko", "cuaca_buruk"]
ANGKA = ["harga_per_orang", "durasi_jam", "kuota"]
HURUF_KECIL = ["tema", "status_data", "tingkat_kesulitan"]


def angka(teks):
    """'Rp 50.000' -> 50000, '2,5' -> 2.5, '' -> None, '2-3 jam' -> None."""
    t = (teks or "").strip().lower().replace("rp", "").replace(" ", "")
    if not t:
        return None
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+", t):
        t = t.replace(",", "")
    t = t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return int(v) if v == int(v) else v


def tanggal(teks):
    """'18/11/2026' atau '2026-11-18' -> date. Selain itu None."""
    t = (teks or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    return None


def baca_csv(path, kolom):
    baris = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            item = {v: (row.get(k) or "").strip() for k, v in kolom.items()}
            if not item.get("nama") and not item.get(list(kolom.values())[0]):
                continue  # baris kosong (misalnya sisa dropdown)
            baris.append(item)
    return baris


def bersihkan_kegiatan(baris):
    hasil = []
    for r in baris:
        if not r["nama"]:
            continue
        r["_tidak_terbaca"] = []
        for f in ANGKA:
            mentah = r[f]
            r[f] = angka(mentah)
            if mentah and r[f] is None:
                r["_tidak_terbaca"].append(f"{f} = '{mentah}'")
        for f in HURUF_KECIL:
            r[f] = r[f].lower()
        r["terakhir_diverifikasi"] = tanggal(r.get("terakhir_diverifikasi", ""))
        r["hari_tutup"] = [h.strip().lower() for h in re.split(r"[;,]|\bdan\b", r["hari_tutup"]) if h.strip()]
        hasil.append(r)
    return hasil


STATUS_DEMO = {"terverifikasi", "lengkap", "sebagian"}


def terapkan_isian_demo(kegiatan, path):
    """MODE DEMO. Isi angka yang kosong dari berkas terpisah (data/isian_demo.csv).
    Angka dari sheet selalu menang. Setiap kegiatan diberi tanda demo supaya hasilnya berlabel."""
    isian = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            isian[r["ID"].strip()] = r
    peta = {"harga_per_orang": "Harga per orang (Rp)", "durasi_jam": "Durasi (jam)", "kuota": "Kuota per sesi"}
    for k in kegiatan:
        k["demo"] = True
        r = isian.get(k["id"])
        if not r:
            continue
        dipakai = []
        for f, kol in peta.items():
            if k.get(f) is None and angka(r.get(kol)) is not None:
                k[f] = angka(r[kol])
                dipakai.append(f)
        # isian demo menggantikan teks yang tidak terbaca untuk kolom yang terisi
        k["_tidak_terbaca"] = [t for t in k["_tidak_terbaca"] if t.split(" =")[0] not in dipakai]
        k["demo_dasar"] = r.get("Dasar isian", "")
    return kegiatan


def periksa(kegiatan, host, hari_ini=None, masa_berlaku_hari=None, demo=False):
    """hari_ini dan masa_berlaku_hari dipakai untuk mengecek verifikasi yang sudah kedaluwarsa.
    Kalau masa_berlaku_hari None (belum diputuskan tim), cek kedaluwarsa dilewati.
    demo=True: status 'sebagian' boleh, persetujuan tampil dan tanggal verifikasi tidak diwajibkan."""
    host_by_id = {h["host_id"]: h for h in host}
    laporan = []
    for k in kegiatan:
        masalah = []
        if demo:
            if k["status_data"] not in STATUS_DEMO:
                masalah.append(f"status data '{k['status_data'] or 'kosong'}' tidak dipakai bahkan di mode demo")
        elif k["status_data"] != "terverifikasi":
            masalah.append(f"status data '{k['status_data'] or 'kosong'}', belum 'terverifikasi'")
        else:
            tgl = k.get("terakhir_diverifikasi")
            if tgl is None:
                masalah.append("kolom 'Terakhir diverifikasi' kosong atau tanggalnya tidak terbaca")
            elif masa_berlaku_hari is not None and hari_ini is not None:
                batas = tgl + timedelta(days=masa_berlaku_hari)
                if hari_ini > batas:
                    masalah.append(f"verifikasi kedaluwarsa sejak {batas.isoformat()}, perlu dicek ulang")
        for f in WAJIB_PLANNER:
            if k.get(f) in (None, ""):
                masalah.append(f"kolom wajib kosong: {f}")
        for t in k["_tidak_terbaca"]:
            masalah.append(f"isi tidak terbaca sebagai angka: {t}")
        if not k["host_id"]:
            masalah.append("tidak ada ID Host")
        elif k["host_id"] not in host_by_id:
            masalah.append(f"ID Host {k['host_id']} tidak ada di tab Host")
        elif not demo and host_by_id[k["host_id"]]["setuju_tampil"].lower() != "ya":
            masalah.append("host belum menyatakan setuju tampil di Pathora")
        kurang_tampil = [f for f in WAJIB_TAMPIL if not k.get(f)]
        laporan.append({
            "id": k["id"],
            "nama": k["nama"],
            "siap_direkomendasikan": not masalah,
            "demo": demo,
            "masalah": masalah,
            "kurang_untuk_tampil_lengkap": kurang_tampil,
        })
    return laporan


def cetak_laporan(laporan):
    siap = [l for l in laporan if l["siap_direkomendasikan"]]
    print(f"Kegiatan terbaca: {len(laporan)}")
    if laporan and laporan[0].get("demo"):
        print("*** MODE DEMO: data belum terverifikasi, sebagian angka adalah estimasi. Bukan untuk wisatawan. ***")
    print(f"Siap direkomendasikan AI: {len(siap)}")
    print()
    for l in laporan:
        tanda = "SIAP" if l["siap_direkomendasikan"] else "BELUM"
        print(f"[{tanda}] {l['id']} {l['nama']}")
        for m in l["masalah"]:
            print(f"    - {m}")
        if l["siap_direkomendasikan"] and l["kurang_untuk_tampil_lengkap"]:
            print("    - belum lengkap untuk ditampilkan: " + ", ".join(l["kurang_untuk_tampil_lengkap"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kegiatan_csv")
    ap.add_argument("host_csv")
    ap.add_argument("--out", default="out")
    ap.add_argument("--masa-berlaku-hari", type=int, default=None,
                    help="berapa hari verifikasi dianggap masih segar (diputuskan tim)")
    ap.add_argument("--hari-ini", default=None, help="YYYY-MM-DD, default hari ini")
    ap.add_argument("--demo", action="store_true",
                    help="MODE DEMO: ikutkan status 'Sebagian', abaikan persetujuan host, hasil diberi label")
    ap.add_argument("--isian-demo", default=None, help="CSV isian angka untuk demo (dipakai bersama --demo)")
    a = ap.parse_args()

    hari_ini = date.fromisoformat(a.hari_ini) if a.hari_ini else date.today()
    kegiatan = bersihkan_kegiatan(baca_csv(a.kegiatan_csv, KEGIATAN_KOLOM))
    host = baca_csv(a.host_csv, HOST_KOLOM)
    if a.demo and a.isian_demo:
        terapkan_isian_demo(kegiatan, a.isian_demo)
    elif a.demo:
        for k in kegiatan:
            k["demo"] = True
    if a.masa_berlaku_hari is None:
        print("PERHATIAN: masa berlaku verifikasi belum ditentukan, jadi cek kedaluwarsa dilewati.\n")
    laporan = periksa(kegiatan, host, hari_ini, a.masa_berlaku_hari, demo=a.demo)
    siap_id = {l["id"] for l in laporan if l["siap_direkomendasikan"]}

    out = Path(a.out)
    out.mkdir(exist_ok=True)
    (out / "kegiatan.json").write_text(json.dumps(kegiatan, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "kegiatan_siap.json").write_text(
        json.dumps([k for k in kegiatan if k["id"] in siap_id], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "laporan.json").write_text(json.dumps(laporan, ensure_ascii=False, indent=2), encoding="utf-8")
    cetak_laporan(laporan)


if __name__ == "__main__":
    main()
