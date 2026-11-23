"""Tes lapisan model bahasa. Model diganti fungsi palsu, jadi tidak butuh API.

Semua data kegiatan di sini FIKTIF (CONTOH), hanya untuk menguji logika kode.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from asisten import jawab  # noqa: E402
from ekstrak import GagalEkstraksi, ekstrak_preferensi, validasi_prefs  # noqa: E402
from narasi import narasi_cadangan, periksa_narasi, tulis_narasi  # noqa: E402
from planner import susun  # noqa: E402


def contoh(id_, nama, harga=50000, jam=3.0, tema="alam"):
    return {"id": id_, "nama": nama, "desa": "Desa Contoh", "tema": tema,
            "harga_per_orang": harga, "durasi_jam": jam, "kuota": 10,
            "tingkat_kesulitan": "mudah", "hari_tutup": []}


DATA = [contoh("A", "CONTOH Trekking Satu"), contoh("B", "CONTOH Tenun Dua", tema="budaya")]
PREFS_JSON = json.dumps({"durasi_hari": 1, "jumlah_orang": 2, "tema": ["alam"],
                         "tingkat_aktivitas": None, "budget_per_hari": None,
                         "tanggal_mulai": None, "catatan": "", "perlu_tanya": []})


class TesValidasi(unittest.TestCase):
    def test_tema_di_luar_daftar_ditolak(self):
        with self.assertRaises(ValueError):
            validasi_prefs({"tema": ["kuliner"]})

    def test_durasi_tidak_masuk_akal_ditolak(self):
        with self.assertRaises(ValueError):
            validasi_prefs({"durasi_hari": 100})

    def test_tanggal_salah_format_ditolak(self):
        with self.assertRaises(ValueError):
            validasi_prefs({"tanggal_mulai": "besok"})

    def test_semua_kosong_boleh(self):
        self.assertIsNone(validasi_prefs({})["durasi_hari"])


class TesEkstrak(unittest.TestCase):
    def test_json_dalam_pagar_kode_terbaca(self):
        llm = lambda s, u: "```json\n" + PREFS_JSON + "\n```"  # noqa: E731
        self.assertEqual(ekstrak_preferensi("x", llm)["durasi_hari"], 1)

    def test_mengulang_kalau_tidak_valid(self):
        jawaban = iter(["bukan json", PREFS_JSON])
        self.assertEqual(ekstrak_preferensi("x", lambda s, u: next(jawaban))["jumlah_orang"], 2)

    def test_gagal_terus_melempar_error(self):
        with self.assertRaises(GagalEkstraksi):
            ekstrak_preferensi("x", lambda s, u: "ngawur")


class TesNarasi(unittest.TestCase):
    def setUp(self):
        self.rencana = susun(DATA, {"durasi_hari": 1, "tema": ["alam"]})

    def test_harga_karangan_ditolak(self):
        self.assertTrue(periksa_narasi("Cuma Rp10.000 per orang", self.rencana, DATA))

    def test_harga_benar_lolos(self):
        self.assertFalse(periksa_narasi("Harganya Rp50.000 per orang", self.rencana, DATA))

    def test_kegiatan_di_luar_rencana_ditolak(self):
        teks = "Kamu juga bisa ke CONTOH Tenun Dua"
        self.assertTrue(periksa_narasi(teks, self.rencana, DATA))

    def test_narasi_model_buruk_diganti_cadangan(self):
        hasil = tulis_narasi(self.rencana, DATA, lambda s, u: "Cuma Rp1.000 saja!")
        self.assertIn("Rp50.000", hasil)
        self.assertNotIn("Rp1.000", hasil)

    def test_narasi_model_baik_dipakai(self):
        teks = "Hari 1: CONTOH Trekking Satu, Rp50.000 per orang."
        self.assertEqual(tulis_narasi(self.rencana, DATA, lambda s, u: teks), teks)

    def test_rencana_kosong_tidak_memanggil_model(self):
        kosong = susun([], {"durasi_hari": 2})
        def llm(s, u):
            raise AssertionError("model tidak boleh dipanggil")
        self.assertIn("belum ada kegiatan terverifikasi", tulis_narasi(kosong, [], llm))
        self.assertIn("belum ada kegiatan terverifikasi", narasi_cadangan(kosong))


class TesJawab(unittest.TestCase):
    def test_durasi_tidak_jelas_bertanya_balik(self):
        prefs = json.dumps({"perlu_tanya": ["Berapa hari?"]})
        hasil = jawab("mau liburan", DATA, lambda s, u: prefs)
        self.assertEqual(hasil["tipe"], "tanya")

    def test_alur_lengkap(self):
        panggilan = iter([PREFS_JSON, "Hari 1: CONTOH Trekking Satu, Rp50.000 per orang."])
        hasil = jawab("1 hari berdua suka alam", DATA, lambda s, u: next(panggilan))
        self.assertEqual(hasil["tipe"], "rencana")
        self.assertEqual(hasil["rencana"]["hari"][0]["kegiatan"][0]["id"], "A")


if __name__ == "__main__":
    unittest.main()
