"""Tes untuk masalah yang ditemukan di laporan uji pertama dengan Gemini (data fiktif berlabel CONTOH)."""
import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from asisten import jawab  # noqa: E402
from ekstrak import ekstrak_preferensi, validasi_prefs  # noqa: E402
from narasi import LABEL_DEMO, tulis_narasi  # noqa: E402
from planner import susun  # noqa: E402


def kegiatan(id, desa="Bugbug", tema="alam", cocok="Keluarga", **ubah):
    k = {"id": id, "nama": f"CONTOH {id}", "desa": desa, "tema": tema, "tingkat_kesulitan": "mudah",
         "harga_per_orang": 10000, "durasi_jam": 2, "kuota": 10, "hari_tutup": [], "cocok_untuk": cocok, "demo": True}
    k.update(ubah)
    return k


class TesLokasiDanTema(unittest.TestCase):
    def test_lokasi_di_luar_data_diberi_catatan(self):
        r = susun([kegiatan("A")], {"durasi_hari": 1, "lokasi_diminta": ["Nusa Penida"]})
        self.assertTrue(any("Nusa Penida" in c for c in r["catatan"]))
        self.assertTrue(any(h["kegiatan"] for h in r["hari"]))  # tetap menawarkan yang ada

    def test_bali_timur_dan_desa_yang_ada_tidak_dikeluhkan(self):
        r = susun([kegiatan("A", desa="Tri Eka Buana (Sidemen)")],
                  {"durasi_hari": 1, "lokasi_diminta": ["Bali timur", "Sidemen", "Karangasem"]})
        self.assertFalse(any("Belum ada kegiatan di" in c for c in r["catatan"]))

    def test_tema_yang_tidak_ada_diberi_catatan(self):
        r = susun([kegiatan("A")], {"durasi_hari": 1, "tema": ["alam", "satwa"]})
        self.assertTrue(any("satwa" in c for c in r["catatan"]))
        self.assertFalse(any("alam" in c for c in r["catatan"]))


class TesKebutuhanKhusus(unittest.TestCase):
    def test_kursi_roda_tidak_direkomendasikan(self):
        r = susun([kegiatan("A")], {"durasi_hari": 3, "kebutuhan_khusus": ["kursi_roda"]})
        self.assertEqual(r["hari"], [])
        self.assertTrue(any("kursi roda" in c for c in r["catatan"]))

    def test_anak_kecil_menyaring_kegiatan_khusus_dewasa(self):
        data = [kegiatan("A", cocok="Keluarga"), kegiatan("B", cocok="Dewasa yang fit")]
        r = susun(data, {"durasi_hari": 2, "kebutuhan_khusus": ["anak_kecil"]})
        ids = [k["id"] for h in r["hari"] for k in h["kegiatan"]]
        self.assertEqual(ids, ["A"])

    def test_alergi_dan_vegetarian_hanya_catatan(self):
        r = susun([kegiatan("A")], {"durasi_hari": 1, "kebutuhan_khusus": ["alergi_makanan"]})
        self.assertTrue(any("makanan" in c for c in r["catatan"]))
        self.assertTrue(any(h["kegiatan"] for h in r["hari"]))

    def test_rombongan_besar_dijelaskan_alasannya(self):
        r = susun([kegiatan("A", kuota=10)], {"durasi_hari": 2, "jumlah_orang": 20})
        self.assertTrue(any("20 orang" in c for c in r["catatan"]))


class TesNarasiMembawaCatatan(unittest.TestCase):
    def test_catatan_dan_label_ditambah_kode_bukan_model(self):
        r = susun([kegiatan("A")], {"durasi_hari": 2, "lokasi_diminta": ["Nusa Penida"]})
        llm = lambda s, u: "Hari 1: CONTOH A, Rp10.000 per orang."
        teks = tulis_narasi(r, [kegiatan("A")], llm)
        self.assertIn("Nusa Penida", teks)
        self.assertIn(LABEL_DEMO, teks)

    def test_model_tidak_menerima_hari_kosong_atau_catatan(self):
        r = susun([kegiatan("A")], {"durasi_hari": 3})
        terima = {}
        def llm(s, u):
            terima["isi"] = json.loads(u)
            return "ok Rp10.000"
        tulis_narasi(r, [kegiatan("A")], llm)
        self.assertNotIn("catatan", terima["isi"])
        self.assertTrue(all(h["kegiatan"] for h in terima["isi"]["hari"]))


class TesTanggalDanLuarCakupan(unittest.TestCase):
    def test_tanggal_lewat_ditolak(self):
        with self.assertRaises(ValueError):
            validasi_prefs({"tanggal_mulai": "2025-05-23"}, hari_ini=date(2026, 11, 23))

    def test_tanggal_lewat_diulang_lalu_berhasil(self):
        jawaban = iter([json.dumps({"durasi_hari": 2, "tanggal_mulai": "2025-05-23"}),
                        json.dumps({"durasi_hari": 2, "tanggal_mulai": "2026-11-24"})])
        p = ekstrak_preferensi("besok 2 hari", lambda s, u: next(jawaban), hari_ini=date(2026, 11, 23))
        self.assertEqual(p["tanggal_mulai"], "2026-11-24")

    def test_tanggal_hari_ini_dikirim_ke_model(self):
        terima = {}
        def llm(s, u):
            terima["u"] = u
            return json.dumps({"durasi_hari": 1})
        ekstrak_preferensi("besok", llm, hari_ini=date(2026, 11, 23))
        self.assertIn("2026-11-23", terima["u"])

    def test_di_luar_cakupan_dijawab_tanpa_rencana(self):
        llm = lambda s, u: json.dumps({"di_luar_cakupan": True})
        h = jawab("rekomendasi hotel", [kegiatan("A")], llm)
        self.assertEqual(h["tipe"], "tanya")
        self.assertIn("hotel", h["pesan"])

    def test_durasi_lebih_dari_14_hari_dijelaskan(self):
        llm = lambda s, u: json.dumps({"durasi_hari": 30})
        h = jawab("30 hari", [kegiatan("A")], llm)
        self.assertIn("14 hari", h["pesan"])


if __name__ == "__main__":
    unittest.main()


class TesTemuanUjiKedua(unittest.TestCase):
    def test_petualangan_memakai_kegiatan_alam_dengan_catatan(self):
        r = susun([kegiatan("A", tema="alam")], {"durasi_hari": 1, "tema": ["petualangan"], "tingkat_aktivitas": "aktif"})
        self.assertTrue(any(h["kegiatan"] for h in r["hari"]))
        self.assertTrue(any("petualangan" in c for c in r["catatan"]))

    def test_tema_ganda_dipisah(self):
        r = susun([kegiatan("A", tema="Alam, Petualangan")], {"durasi_hari": 1, "tema": ["petualangan"]})
        self.assertTrue(any(h["kegiatan"] for h in r["hari"]))
        self.assertFalse(any("petualangan" in c for c in r["catatan"]))

    def test_santai_tidak_menawarkan_kegiatan_sangat_lama(self):
        data = [kegiatan("A", durasi_jam=12), kegiatan("B", durasi_jam=2, desa="Desa B")]
        r = susun(data, {"durasi_hari": 2, "tingkat_aktivitas": "santai"})
        ids = [k["id"] for h in r["hari"] for k in h["kegiatan"]]
        self.assertEqual(ids, ["B"])

    def test_aktif_boleh_kegiatan_lama(self):
        r = susun([kegiatan("A", durasi_jam=12)], {"durasi_hari": 1, "tingkat_aktivitas": "aktif"})
        self.assertEqual(r["hari"][0]["kegiatan"][0]["id"], "A")

    def test_minat_khusus_diprioritaskan(self):
        data = [kegiatan("A", nama="Pertunjukan tari", desa="Desa A"),
                kegiatan("B", nama="Belajar membuat garam", desa="Desa Z")]
        r = susun(data, {"durasi_hari": 1, "minat_khusus": ["garam"]})
        self.assertEqual(r["hari"][0]["kegiatan"][0]["id"], "B")

    def test_minat_yang_tidak_ada_diberi_catatan(self):
        r = susun([kegiatan("A")], {"durasi_hari": 1, "minat_khusus": ["penyu"]})
        self.assertTrue(any("penyu" in c for c in r["catatan"]))

    def test_harga_tanpa_rp_yang_salah_ditolak(self):
        from narasi import periksa_narasi
        r = susun([kegiatan("A")], {"durasi_hari": 1})
        self.assertTrue(periksa_narasi("Biayanya 99.000 per orang", r, [kegiatan("A")]))
        self.assertFalse(periksa_narasi("Biayanya 10.000 per orang", r, [kegiatan("A")]))

    def test_tahun_tidak_dianggap_harga(self):
        from narasi import periksa_narasi
        r = susun([kegiatan("A")], {"durasi_hari": 1})
        self.assertFalse(periksa_narasi("Data tahun 2026 ya. Rp10.000", r, [kegiatan("A")]))

    def test_minat_khusus_divalidasi(self):
        p = validasi_prefs({"minat_khusus": [" Garam ", "Arak"]})
        self.assertEqual(p["minat_khusus"], ["garam", "arak"])
        with self.assertRaises(ValueError):
            validasi_prefs({"minat_khusus": "garam"})


class TesTemuanUjiKetiga(unittest.TestCase):
    def test_minat_terlalu_umum_diabaikan(self):
        r = susun([kegiatan("A", tema="budaya")], {"durasi_hari": 1, "minat_khusus": ["budaya lokal tersembunyi", "unik"]})
        self.assertFalse(any("berkaitan dengan" in c for c in r["catatan"]))

    def test_minat_spesifik_tetap_dipakai(self):
        r = susun([kegiatan("A")], {"durasi_hari": 1, "minat_khusus": ["penyu"]})
        self.assertTrue(any("penyu" in c for c in r["catatan"]))

    def test_minat_ada_di_data_tapi_tersaring_dijelaskan(self):
        data = [kegiatan("A", nama="Trekking ke air terjun", tingkat_kesulitan="sedang"),
                kegiatan("B", nama="Wisata sawah", desa="Desa B")]
        r = susun(data, {"durasi_hari": 1, "tingkat_aktivitas": "santai", "minat_khusus": ["air terjun"]})
        ids = [k["id"] for h in r["hari"] for k in h["kegiatan"]]
        self.assertEqual(ids, ["B"])
        self.assertTrue(any("air terjun" in c and "tidak ditawarkan" in c for c in r["catatan"]))

    def test_durasi_memakai_koma(self):
        from narasi import narasi_cadangan
        r = susun([kegiatan("A", durasi_jam=1.5)], {"durasi_hari": 1})
        self.assertIn("1,5 jam", narasi_cadangan(r))

    def test_model_menerima_durasi_berkoma(self):
        terima = {}
        def llm(s, u):
            terima["isi"] = json.loads(u)
            return "ok Rp10.000"
        r = susun([kegiatan("A", durasi_jam=1.5)], {"durasi_hari": 1})
        tulis_narasi(r, [kegiatan("A")], llm)
        self.assertEqual(terima["isi"]["hari"][0]["kegiatan"][0]["durasi_jam"], "1,5")
