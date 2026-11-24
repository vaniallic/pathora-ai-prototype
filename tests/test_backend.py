"""Tes backend (auth, database, endpoint rencana). Model bahasa dipalsukan, jadi tidak butuh API.

Butuh paket di backend/requirements.txt (fastapi, PyJWT) plus httpx untuk TestClient.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AKAR))
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = str(Path(_tmp) / "impor.db")  # database modul tidak menyentuh berkas asli

try:
    from fastapi.testclient import TestClient
    from backend.main import create_app
except ImportError as e:  # paket backend belum terpasang
    raise unittest.SkipTest(f"lewati tes backend: {e}")


def llm_palsu(balasan_prefs, catat=None):
    """Balasan pertama: JSON preferensi. Balasan berikutnya: narasi tanpa angka."""
    def llm(system, user):
        if catat is not None:
            catat.append(user)
        if "Permintaan wisatawan" in user:
            return json.dumps(balasan_prefs)
        return "Ini rencana perjalananmu di Bali timur."
    return llm


PREFS = {"durasi_hari": 2, "jumlah_orang": 2, "tema": ["alam"], "tingkat_aktivitas": None,
         "budget_per_hari": None, "tanggal_mulai": None, "catatan": "", "perlu_tanya": []}


class TesBackend(unittest.TestCase):
    def setUp(self):
        self.catat = []
        self.prefs = dict(PREFS)
        db = Path(tempfile.mkdtemp()) / "tes.db"
        self.app = create_app(db_path=db, pembuat_llm=lambda: llm_palsu(self.prefs, self.catat), demo=True)
        self.c = TestClient(self.app)

    def daftar(self, email="kevin@contoh.id", password="rahasia123"):
        r = self.c.post("/api/auth/signup", json={"nama": "Kevin", "email": email, "password": password})
        self.assertEqual(r.status_code, 201, r.text)
        return {"Authorization": "Bearer " + r.json()["token"]}

    def test_health_dan_kegiatan_publik_tanpa_kontak_host(self):
        self.assertEqual(self.c.get("/api/health").json()["status"], "ok")
        keg = self.c.get("/api/kegiatan").json()
        self.assertTrue(keg)
        self.assertNotIn("host_id", keg[0])
        self.assertNotIn("sumber", keg[0])

    def test_signup_login_me(self):
        self.daftar()
        r = self.c.post("/api/auth/login", json={"email": "KEVIN@contoh.id ", "password": "rahasia123"})
        self.assertEqual(r.status_code, 200)
        me = self.c.get("/api/auth/me", headers={"Authorization": "Bearer " + r.json()["token"]})
        self.assertEqual(me.json()["email"], "kevin@contoh.id")
        self.assertNotIn("password_hash", me.json())

    def test_password_tidak_disimpan_polos(self):
        self.daftar()
        p = self.app.state.db.pengguna_by_email("kevin@contoh.id")
        self.assertNotIn("rahasia123", p["password_hash"])
        self.assertTrue(p["password_hash"].startswith("scrypt$"))

    def test_email_ganda_dan_input_tidak_valid(self):
        self.daftar()
        r = self.c.post("/api/auth/signup", json={"nama": "X", "email": "kevin@contoh.id", "password": "rahasia123"})
        self.assertEqual(r.status_code, 409)
        r = self.c.post("/api/auth/signup", json={"nama": "X", "email": "bukan-email", "password": "rahasia123"})
        self.assertEqual(r.status_code, 422)
        r = self.c.post("/api/auth/signup", json={"nama": "X", "email": "a@b.id", "password": "pendek"})
        self.assertEqual(r.status_code, 422)

    def test_login_salah_dan_dibatasi(self):
        self.daftar()
        for _ in range(5):
            r = self.c.post("/api/auth/login", json={"email": "kevin@contoh.id", "password": "salahsalah"})
            self.assertEqual(r.status_code, 401)
        r = self.c.post("/api/auth/login", json={"email": "kevin@contoh.id", "password": "rahasia123"})
        self.assertEqual(r.status_code, 429)

    def test_rencana_butuh_login(self):
        self.assertEqual(self.c.post("/api/rencana", json={"teks": "2 hari"}).status_code, 401)
        r = self.c.get("/api/rencana", headers={"Authorization": "Bearer token-ngawur"})
        self.assertEqual(r.status_code, 401)

    def test_rencana_tersimpan_dan_hanya_milik_sendiri(self):
        h = self.daftar()
        r = self.c.post("/api/rencana", json={"teks": "2 hari berdua, suka alam"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        hasil = r.json()
        self.assertEqual(hasil["tipe"], "rencana")
        self.assertIn("Versi prototype", hasil["pesan"])  # label demo ditambahkan kode
        riwayat = self.c.get("/api/rencana", headers=h).json()
        self.assertEqual(len(riwayat), 1)
        self.assertEqual(riwayat[0]["rencana"]["hari"][0]["hari"], 1)

        h2 = self.daftar(email="orang.lain@contoh.id")
        self.assertEqual(self.c.get(f"/api/rencana/{hasil['id']}", headers=h2).status_code, 404)
        self.assertEqual(self.c.delete(f"/api/rencana/{hasil['id']}", headers=h2).status_code, 404)
        self.assertEqual(self.c.delete(f"/api/rencana/{hasil['id']}", headers=h).status_code, 204)

    def test_tanya_balik_lalu_dilanjutkan(self):
        h = self.daftar()
        self.prefs.update(durasi_hari=None, perlu_tanya=["Berapa hari kamu di Bali?"])
        r1 = self.c.post("/api/rencana", json={"teks": "pengen lihat air terjun"}, headers=h).json()
        self.assertEqual(r1["tipe"], "tanya")
        self.prefs.update(durasi_hari=2, perlu_tanya=[])
        r2 = self.c.post("/api/rencana", json={"teks": "2 hari", "lanjutan_dari": r1["id"]}, headers=h).json()
        self.assertEqual(r2["tipe"], "rencana")
        self.assertIn("pengen lihat air terjun\n2 hari", self.catat[-2])  # permintaan awal ikut terkirim

    def test_model_gagal_tidak_membuat_server_error(self):
        def rusak():
            raise RuntimeError("ANTHROPIC_API_KEY belum diatur")
        app = create_app(db_path=Path(tempfile.mkdtemp()) / "x.db", pembuat_llm=rusak, demo=True)
        c = TestClient(app)
        tok = c.post("/api/auth/signup", json={"nama": "K", "email": "k@contoh.id", "password": "rahasia123"}).json()["token"]
        auth = {"Authorization": "Bearer " + tok}
        # model mati: permintaan tetap dipahami lewat kata kunci, rencana tetap keluar
        r = c.post("/api/rencana", json={"teks": "3 hari berdua, suka air terjun, jangan yang berat"}, headers=auth)
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["tipe"], "rencana")
        self.assertTrue(j["tanpa_model"])
        self.assertEqual((j["prefs"]["durasi_hari"], j["prefs"]["jumlah_orang"]), (3, 2))
        self.assertEqual(j["prefs"]["tema"], ["alam"])
        self.assertEqual(j["prefs"]["tingkat_aktivitas"], "santai")
        # tanpa durasi: bertanya balik
        r = c.post("/api/rencana", json={"teks": "pengen lihat pura"}, headers=auth)
        self.assertEqual(r.json()["tipe"], "tanya")


if __name__ == "__main__":
    unittest.main()
