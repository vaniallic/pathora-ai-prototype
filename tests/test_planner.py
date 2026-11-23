"""Tes penyusun itinerary.

PENTING: semua data di file ini adalah CONTOH FIKTIF untuk menguji logika kode.
Ini bukan data Pathora yang asli dan jangan dipakai di aplikasi atau presentasi.
"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from load_data import angka, periksa, tanggal  # noqa: E402
from planner import susun  # noqa: E402


def contoh(id_, desa="Desa Contoh A", tema="alam", harga=50000, jam=3.0, kuota=10,
           sulit="mudah", tutup=None):
    return {
        "id": id_, "nama": f"CONTOH {id_}", "desa": desa, "tema": tema,
        "harga_per_orang": harga, "durasi_jam": jam, "kuota": kuota,
        "tingkat_kesulitan": sulit, "hari_tutup": tutup or [],
    }


class TesAngka(unittest.TestCase):
    def test_format(self):
        self.assertEqual(angka("Rp 50.000"), 50000)
        self.assertEqual(angka("2,5"), 2.5)
        self.assertEqual(angka("50,000"), 50000)
        self.assertIsNone(angka(""))
        self.assertIsNone(angka("2-3 jam"))


class TesPeriksa(unittest.TestCase):
    def test_belum_terverifikasi_tidak_siap(self):
        k = {**contoh("X1"), "status_data": "sebagian", "host_id": "H1", "_tidak_terbaca": [],
             "cara_booking": "", "titik_kumpul": "", "cara_ke_sana": "", "kondisi_jalan": "",
             "aturan_budaya": "", "risiko": "", "cuaca_buruk": ""}
        host = [{"host_id": "H1", "setuju_tampil": "Ya"}]
        hasil = periksa([k], host)[0]
        self.assertFalse(hasil["siap_direkomendasikan"])

    def test_host_belum_setuju_tidak_siap(self):
        k = {**contoh("X2"), "status_data": "terverifikasi", "host_id": "H1", "_tidak_terbaca": [],
             "cara_booking": "a", "titik_kumpul": "a", "cara_ke_sana": "a", "kondisi_jalan": "a",
             "aturan_budaya": "a", "risiko": "a", "cuaca_buruk": "a"}
        host = [{"host_id": "H1", "setuju_tampil": "Belum jelas"}]
        self.assertFalse(periksa([k], host)[0]["siap_direkomendasikan"])

    def _lengkap(self, id_, tgl):
        return {**contoh(id_), "status_data": "terverifikasi", "host_id": "H1", "_tidak_terbaca": [],
                "terakhir_diverifikasi": tgl,
                "cara_booking": "a", "titik_kumpul": "a", "cara_ke_sana": "a", "kondisi_jalan": "a",
                "aturan_budaya": "a", "risiko": "a", "cuaca_buruk": "a"}

    def test_lengkap_dan_setuju_siap(self):
        k = self._lengkap("X3", date(2026, 11, 1))
        host = [{"host_id": "H1", "setuju_tampil": "Ya"}]
        self.assertTrue(periksa([k], host)[0]["siap_direkomendasikan"])

    def test_terverifikasi_tanpa_tanggal_tidak_siap(self):
        k = self._lengkap("X4", None)
        host = [{"host_id": "H1", "setuju_tampil": "Ya"}]
        self.assertFalse(periksa([k], host)[0]["siap_direkomendasikan"])

    def test_verifikasi_kedaluwarsa_tidak_siap(self):
        # angka 90 hari di sini hanya untuk uji kode, bukan keputusan tim
        k = self._lengkap("X5", date(2026, 1, 1))
        host = [{"host_id": "H1", "setuju_tampil": "Ya"}]
        hasil = periksa([k], host, hari_ini=date(2026, 11, 19), masa_berlaku_hari=90)[0]
        self.assertFalse(hasil["siap_direkomendasikan"])

    def test_verifikasi_masih_berlaku_siap(self):
        k = self._lengkap("X6", date(2026, 11, 1))
        host = [{"host_id": "H1", "setuju_tampil": "Ya"}]
        hasil = periksa([k], host, hari_ini=date(2026, 11, 19), masa_berlaku_hari=90)[0]
        self.assertTrue(hasil["siap_direkomendasikan"])

    def test_masa_berlaku_belum_ditentukan_lewati_cek(self):
        k = self._lengkap("X7", date(2020, 1, 1))
        host = [{"host_id": "H1", "setuju_tampil": "Ya"}]
        hasil = periksa([k], host, hari_ini=date(2026, 11, 19), masa_berlaku_hari=None)[0]
        self.assertTrue(hasil["siap_direkomendasikan"])


class TesTanggal(unittest.TestCase):
    def test_format(self):
        self.assertEqual(tanggal("18/11/2026"), date(2026, 11, 18))
        self.assertEqual(tanggal("2026-11-18"), date(2026, 11, 18))
        self.assertIsNone(tanggal(""))
        self.assertIsNone(tanggal("kemarin"))


class TesPlanner(unittest.TestCase):
    def test_tidak_ada_data_tidak_mengarang(self):
        hasil = susun([], {"durasi_hari": 2})
        self.assertEqual(hasil["hari"], [])
        self.assertTrue(hasil["catatan"])

    def test_filter_tema(self):
        data = [contoh("A", tema="alam"), contoh("B", tema="budaya")]
        hasil = susun(data, {"durasi_hari": 1, "tema": ["budaya"]})
        ids = [k["id"] for h in hasil["hari"] for k in h["kegiatan"]]
        self.assertEqual(ids, ["B"])

    def test_budget_per_hari(self):
        data = [contoh("A", harga=80000), contoh("B", harga=80000)]
        hasil = susun(data, {"durasi_hari": 1, "budget_per_hari": 100000})
        self.assertEqual(len(hasil["hari"][0]["kegiatan"]), 1)

    def test_batas_jam_per_hari(self):
        data = [contoh("A", jam=5), contoh("B", jam=5)]
        hasil = susun(data, {"durasi_hari": 2})
        self.assertEqual([len(h["kegiatan"]) for h in hasil["hari"]], [1, 1])

    def test_tingkat_aktivitas_santai_menolak_berat(self):
        data = [contoh("A", sulit="berat")]
        hasil = susun(data, {"durasi_hari": 1, "tingkat_aktivitas": "santai"})
        self.assertEqual(hasil["hari"], [])

    def test_desa_beda_tanpa_data_jarak_tidak_digabung(self):
        data = [contoh("A", desa="Desa A"), contoh("B", desa="Desa B")]
        hasil = susun(data, {"durasi_hari": 1})
        self.assertEqual(len(hasil["hari"][0]["kegiatan"]), 1)

    def test_desa_beda_dengan_data_jarak_boleh_digabung(self):
        data = [contoh("A", desa="Desa A"), contoh("B", desa="Desa B")]
        hasil = susun(data, {"durasi_hari": 1}, jarak={("Desa A", "Desa B"): 30})
        self.assertEqual(len(hasil["hari"][0]["kegiatan"]), 2)

    def test_jarak_terlalu_jauh_tidak_digabung(self):
        data = [contoh("A", desa="Desa A"), contoh("B", desa="Desa B")]
        hasil = susun(data, {"durasi_hari": 1}, jarak={("Desa A", "Desa B"): 200})
        self.assertEqual(len(hasil["hari"][0]["kegiatan"]), 1)

    def test_hari_tutup_dihormati(self):
        # 2026-11-23 adalah hari Senin
        data = [contoh("A", tutup=["senin"])]
        hasil = susun(data, {"durasi_hari": 1, "tanggal_mulai": "2026-11-23"})
        self.assertEqual(hasil["hari"][0]["kegiatan"], [])
        self.assertTrue(hasil["catatan"])

    def test_kuota_lebih_kecil_dari_rombongan(self):
        data = [contoh("A", kuota=2)]
        hasil = susun(data, {"durasi_hari": 1, "jumlah_orang": 5})
        self.assertFalse(any(h["kegiatan"] for h in hasil["hari"]))
        self.assertTrue(any("kuota" in c for c in hasil["catatan"]))

    def test_kegiatan_tidak_dipakai_dua_kali(self):
        data = [contoh("A")]
        hasil = susun(data, {"durasi_hari": 2})
        semua = [k["id"] for h in hasil["hari"] for k in h["kegiatan"]]
        self.assertEqual(semua, ["A"])


if __name__ == "__main__":
    unittest.main()


class TesModeDemo(unittest.TestCase):
    def _kegiatan(self, **ubah):
        k = {"id": "X1", "nama": "CONTOH Kegiatan", "desa": "Desa A", "tema": "alam",
             "tingkat_kesulitan": "mudah", "harga_per_orang": 50000, "durasi_jam": 2,
             "kuota": 10, "hari_tutup": [], "demo": True}
        k.update(ubah)
        return k

    def test_hasil_demo_diberi_tanda(self):
        r = susun([self._kegiatan()], {"durasi_hari": 1})
        self.assertTrue(r.get("demo"))

    def test_tanpa_demo_tidak_ada_tanda(self):
        k = self._kegiatan()
        del k["demo"]
        self.assertNotIn("demo", susun([k], {"durasi_hari": 1}))

    def test_kegiatan_sehari_penuh_jadi_satu_satunya_kegiatan(self):
        panjang = self._kegiatan(id="X2", durasi_jam=10.5, desa="Desa A")
        pendek = self._kegiatan(id="X3", desa="Desa A")
        r = susun([panjang, pendek], {"durasi_hari": 2})
        hari1 = [k["id"] for k in r["hari"][0]["kegiatan"]]
        self.assertEqual(len(hari1), 1)

    def test_narasi_cadangan_memuat_label_demo(self):
        import narasi
        r = susun([self._kegiatan()], {"durasi_hari": 1})
        self.assertIn(narasi.LABEL_DEMO, narasi.narasi_cadangan(r))

    def test_total_biaya_menghitung_kegiatan_sehari_penuh(self):
        a = self._kegiatan(id="X4", durasi_jam=12, harga_per_orang=40000, desa="Desa A")
        b = self._kegiatan(id="X5", durasi_jam=10.5, harga_per_orang=1500000, desa="Desa B")
        r = susun([a, b], {"durasi_hari": 2})
        self.assertEqual(r["total_biaya_per_orang"], 1540000)
