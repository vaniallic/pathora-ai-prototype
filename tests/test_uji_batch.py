"""Tes skrip uji batch dengan model palsu (tanpa internet)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import uji_batch  # noqa: E402

DATA = [{"id": "X1", "nama": "CONTOH A", "desa": "D", "tema": "alam", "tingkat_kesulitan": "mudah",
         "harga_per_orang": 10000, "durasi_jam": 2, "kuota": 10, "hari_tutup": [], "demo": True}]
KASUS = [
    {"ID": "T1", "Permintaan": "1 hari alam", "Harapan tipe": "rencana", "Harapan hari": "1",
     "Harapan tema": "alam", "Yang diperiksa manual": ""},
    {"ID": "T2", "Permintaan": "halo", "Harapan tipe": "tanya", "Harapan hari": "",
     "Harapan tema": "", "Yang diperiksa manual": ""},
]


def llm_palsu(system, user):
    if "halo" in user:
        return json.dumps({"perlu_tanya": ["Berapa hari?"]})
    if user.startswith("{"):  # tahap narasi menerima JSON rencana
        raise RuntimeError("tidak dipakai")
    return json.dumps({"durasi_hari": 1, "tema": ["alam"]})


class TesUjiBatch(unittest.TestCase):
    def test_jalan_dan_menulis_laporan(self):
        hasil = uji_batch.jalankan(KASUS, DATA, DATA, llm_palsu, tidur=lambda s: None)
        self.assertEqual([x["hasil"]["tipe"] for x in hasil], ["rencana", "tanya"])
        with tempfile.TemporaryDirectory() as d:
            n = uji_batch.tulis_laporan(hasil, d)
            self.assertEqual(n, 0)
            self.assertTrue((Path(d) / "laporan_uji.md").exists())
            self.assertTrue((Path(d) / "laporan_uji.csv").exists())

    def test_temuan_kalau_harapan_tidak_sesuai(self):
        kasus = dict(KASUS[1], **{"Harapan tipe": "rencana"})
        hasil = uji_batch.jalankan([kasus], DATA, DATA, llm_palsu, tidur=lambda s: None)
        self.assertTrue(any("harusnya menghasilkan rencana" in t for t in hasil[0]["temuan"]))

    def test_kuota_kurang_terdeteksi(self):
        data = [dict(DATA[0], kuota=3)]
        kasus = dict(KASUS[0])
        h = {"tipe": "rencana", "prefs": {"durasi_hari": 1, "tema": ["alam"], "jumlah_orang": 20, "budget_per_hari": None},
             "rencana": {"hari": [{"hari": 1, "kegiatan": [{"id": "X1", "nama": "CONTOH A", "desa": "D", "durasi_jam": 2, "harga_per_orang": 1}]}], "demo": True,
                         "total_biaya_per_orang": 1, "catatan": []}, "pesan": "x"}
        temuan = uji_batch.periksa_otomatis(kasus, h, data)
        self.assertTrue(any("kuota" in t for t in temuan))


if __name__ == "__main__":
    unittest.main()
