"""Tes P2 pemesanan (BACKEND-BRIEF bagian 6): trip, pengajuan, keputusan host, kuota sesi, hari tutup,
patungan, pembayaran simulasi, payout, paspor, paket Plus. Model bahasa tidak dipakai."""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

AKAR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AKAR))
os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.mkdtemp()) / "impor.db"))

try:
    from fastapi.testclient import TestClient
    from backend.main import create_app
    from backend.pemesanan import hitung_pelunasan
except ImportError as e:
    raise unittest.SkipTest(f"lewati tes backend: {e}")

from backend.kalender import fase_bulan, fase_pada  # noqa: E402


def _bebas(mulai):
    """Tanggal pertama sejak `mulai` yang hari itu dan besoknya bukan purnama/tilem (supaya tes tidak bergantung bulan)."""
    d = mulai
    while fase_pada(d) or fase_pada(d + timedelta(days=1)):
        d += timedelta(days=1)
    return d


NANTI = _bebas(date.today() + timedelta(days=30)).isoformat()
LUSA = (date.fromisoformat(NANTI) + timedelta(days=1)).isoformat()
KEMARIN = (date.today() - timedelta(days=1)).isoformat()


def llm_mati():
    def llm(system, user):
        raise RuntimeError("tidak dipakai")
    return llm


class TesPelunasan(unittest.TestCase):
    def test_greedy_sama_dengan_store_js(self):
        # A bayar 300 untuk bertiga, B bayar 60 untuk A dan B
        h = hitung_pelunasan([1, 2, 3], [{"jumlah": 300, "dibayar_oleh": 1, "dibagi_ke": [1, 2, 3]},
                                          {"jumlah": 60, "dibayar_oleh": 2, "dibagi_ke": [1, 2]}])
        saldo = {s["id"]: s["saldo"] for s in h["saldo"]}
        self.assertEqual(saldo, {1: 170, 2: -70, 3: -100})
        self.assertEqual(h["transfer"], [{"dari_id": 3, "ke_id": 1, "jumlah": 100},
                                         {"dari_id": 2, "ke_id": 1, "jumlah": 70}])

    def test_tanpa_pengeluaran(self):
        self.assertEqual(hitung_pelunasan([1, 2], [])["transfer"], [])


class Dasar(unittest.TestCase):
    def setUp(self):
        self.app = create_app(db_path=Path(tempfile.mkdtemp()) / "p.db", pembuat_llm=llm_mati, demo=True)
        self.c = TestClient(self.app)
        self.n = 0

    def akun(self, nama="Maya Putri", **lain):
        self.n += 1
        r = self.c.post("/api/auth/signup", json={"nama": nama, "email": f"u{self.n}@contoh.id",
                                                  "password": "rahasia123", **lain})
        self.assertEqual(r.status_code, 201, r.text)
        return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["pengguna"]

    def host(self, host_id="H04"):
        h, u = self.akun("Wayan Sudarta", peran="host", komunitas="Pokdarwis Desa Selumbung")
        r = self.c.post("/api/host/klaim", json={"host_id": host_id}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        return h, u

    def trip(self, h, **lain):
        r = self.c.post("/api/trips", json={"nama": "Trip Bali", "tanggal_mulai": NANTI, "tanggal_akhir": LUSA, **lain},
                        headers=h)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def item(self, h, tid, kid="K04", tgl=NANTI, **lain):
        return self.c.post(f"/api/trips/{tid}/items", json={"kegiatan_id": kid, "tanggal": tgl, **lain}, headers=h)


class TesTrip(Dasar):
    def test_buat_gabung_dan_privasi(self):
        h1, u1 = self.akun()
        t = self.trip(h1)
        self.assertEqual(t["bendahara_id"], u1["id"])
        self.assertTrue(t["kode"].startswith("bali-"))
        h2, _ = self.akun("Sari Wulan")
        self.assertEqual(self.c.get(f"/api/trips/{t['id']}", headers=h2).status_code, 404)  # bukan anggota
        j = self.c.post("/api/trips/join", json={"kode": t["kode"].upper()}, headers=h2).json()
        self.assertEqual(len(j["anggota"]), 2)
        self.assertNotIn("email", j["anggota"][0])
        self.assertEqual(self.c.post("/api/trips/join", json={"kode": "bali-zzzz"}, headers=h2).status_code, 404)
        self.assertEqual(len(self.c.get("/api/trips", headers=h2).json()), 1)

    def test_ubah_dan_bendahara_harus_anggota(self):
        h, _ = self.akun()
        t = self.trip(h)
        r = self.c.patch(f"/api/trips/{t['id']}", json={"nama": "Liburan", "bendahara_id": 999}, headers=h)
        self.assertEqual(r.status_code, 422)
        r = self.c.patch(f"/api/trips/{t['id']}", json={"tanggal_akhir": KEMARIN}, headers=h)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.c.patch(f"/api/trips/{t['id']}", json={"nama": "Liburan"}, headers=h).json()["nama"],
                         "Liburan")

    def test_hari_sibuk_dan_acara(self):
        h, _ = self.akun()
        t = self.trip(h)
        self.assertEqual(self.c.put(f"/api/trips/{t['id']}/saya", json={"hari_sibuk": [LUSA, NANTI, NANTI]},
                                    headers=h).json()["hari_sibuk"], [NANTI, LUSA])
        a = self.c.post(f"/api/trips/{t['id']}/events", json={"tanggal": NANTI, "jam": "19:00",
                                                               "judul": "Makan malam"}, headers=h).json()
        self.assertEqual(len(self.c.get(f"/api/trips/{t['id']}", headers=h).json()["acara"]), 1)
        self.assertEqual(self.c.delete(f"/api/trips/{t['id']}/events/{a['id']}", headers=h).status_code, 204)


class TesItem(Dasar):
    def test_aturan_tambah_item(self):
        h, _ = self.akun()
        t = self.trip(h)
        r = self.item(h, t["id"], jumlah_orang=2)
        self.assertEqual(r.status_code, 201, r.text)
        it = r.json()
        self.assertEqual((it["status"], it["jumlah_orang"]), ("draft", 2))
        self.assertEqual(it["biaya"], it["harga_per_orang"] * 2)  # harga dari data, bukan dari pengguna
        self.assertTrue(it["demo"])
        self.assertNotIn("kode_hadir", it)
        self.assertEqual(self.item(h, t["id"]).status_code, 409)                       # duplikat
        self.assertEqual(self.item(h, t["id"], kid="K99").status_code, 404)            # tidak dikenal
        self.assertEqual(self.item(h, t["id"], tgl=KEMARIN).status_code, 422)          # sudah lewat
        self.assertEqual(self.item(h, t["id"], kid="K06", jam="25:00").status_code, 422)
        self.assertEqual(self.item(h, t["id"], kid="K06", jumlah_orang=50).status_code, 422)  # melebihi kuota

    def test_rentang_trip_melebar(self):
        h, _ = self.akun()
        t = self.trip(h)
        jauh = (date.today() + timedelta(days=40)).isoformat()
        self.item(h, t["id"], tgl=jauh)
        self.assertEqual(self.c.get(f"/api/trips/{t['id']}", headers=h).json()["tanggal_akhir"], jauh)

    def test_jumlah_orang_default_anggota(self):
        h, _ = self.akun()
        t = self.trip(h)
        h2, _ = self.akun("Sari")
        self.c.post("/api/trips/join", json={"kode": t["kode"]}, headers=h2)
        self.assertEqual(self.item(h, t["id"]).json()["jumlah_orang"], 2)


class TesAlurHost(Dasar):
    def ajukan(self, h, kid="K04", orang=2, jam="09:00"):
        t = self.trip(h)
        it = self.item(h, t["id"], kid=kid, jumlah_orang=orang, jam=jam).json()
        r = self.c.post(f"/api/trips/{t['id']}/items/{it['id']}/request", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "diajukan")
        return t, it

    def test_ajukan_setujui_bayar_stempel(self):
        hw, uw = self.akun()
        hh, _ = self.host("H04")  # H04 mengelola K04 dan K05
        t, it = self.ajukan(hw)
        masuk = self.c.get("/api/host/requests", headers=hh).json()
        self.assertEqual([m["id"] for m in masuk], [it["id"]])
        self.assertEqual(masuk[0]["nama_pengaju"], "Maya P.")       # nama pendek, tanpa email
        self.assertNotIn("email", masuk[0])
        self.assertEqual(self.c.post(f"/api/trips/{t['id']}/pay", json={}, headers=hw).status_code, 409)  # belum disetujui
        r = self.c.post(f"/api/host/requests/{it['id']}/decision", json={"setuju": True}, headers=hh)
        self.assertEqual(r.json()["status"], "disetujui")
        self.assertEqual(self.c.post(f"/api/host/requests/{it['id']}/decision", json={"setuju": False},
                                     headers=hh).status_code, 409)  # sudah diputuskan
        self.assertEqual(self.c.delete(f"/api/trips/{t['id']}/items/{it['id']}", headers=hw).status_code, 409)
        b = self.c.post(f"/api/trips/{t['id']}/pay", json={}, headers=hw).json()
        self.assertTrue(b["simulasi"])
        self.assertEqual(b["dibayar"], [it["id"]])
        payout = self.c.get("/api/host/payouts", headers=hh).json()
        self.assertEqual(payout["total"], it["biaya"])
        kode = [m for m in self.c.get("/api/host/requests", headers=hh).json() if m["id"] == it["id"]][0]["kode_hadir"]
        self.assertTrue(kode.startswith("PA-"))
        self.assertEqual(self.c.post("/api/passport/stamp", json={"kode": "PA-SALAH"}, headers=hw).status_code, 404)
        h_lain, _ = self.akun("Orang Lain")
        self.assertEqual(self.c.post("/api/passport/stamp", json={"kode": kode}, headers=h_lain).status_code, 404)
        self.assertEqual(self.c.post("/api/passport/stamp", json={"kode": kode.lower()}, headers=hw).status_code, 201)
        self.assertEqual(self.c.post("/api/passport/stamp", json={"kode": kode}, headers=hw).status_code, 409)
        self.assertEqual([s["kegiatan_id"] for s in self.c.get("/api/passport", headers=hw).json()], ["K04"])

    def test_hanya_host_pemilik(self):
        hw, _ = self.akun()
        h_lain, _ = self.host("H01")  # bukan pemilik K04
        _, it = self.ajukan(hw)
        self.assertEqual(self.c.get("/api/host/requests", headers=h_lain).json(), [])
        self.assertEqual(self.c.post(f"/api/host/requests/{it['id']}/decision", json={"setuju": True},
                                     headers=h_lain).status_code, 404)
        self.assertEqual(self.c.post(f"/api/host/requests/{it['id']}/decision", json={"setuju": True},
                                     headers=hw).status_code, 403)  # wisatawan
        self.assertEqual(self.c.post("/api/host/klaim", json={"host_id": "H01"}, headers=self.host("H02")[0]).status_code,
                         409)  # sudah diklaim akun lain
        self.assertEqual(self.c.post("/api/host/klaim", json={"host_id": "H04"}, headers=hw).status_code, 403)

    def test_kuota_sesi(self):
        hh, _ = self.host("H04")  # K04 kuota demo 10
        hw1, _ = self.akun()
        hw2, _ = self.akun("Budi")
        _, it1 = self.ajukan(hw1, orang=8)
        _, it2 = self.ajukan(hw2, orang=3)
        self.c.post(f"/api/host/requests/{it1['id']}/decision", json={"setuju": True}, headers=hh)
        r = self.c.post(f"/api/host/requests/{it2['id']}/decision", json={"setuju": True}, headers=hh)
        self.assertEqual(r.status_code, 409)
        self.assertIn("Kuota", r.json()["detail"])
        hw3, _ = self.akun("Citra")
        _, it3 = self.ajukan(hw3, orang=3, jam="14:00")  # sesi lain
        self.assertEqual(self.c.post(f"/api/host/requests/{it3['id']}/decision", json={"setuju": True},
                                     headers=hh).json()["status"], "disetujui")

    def test_hari_tutup(self):
        hh, _ = self.host("H04")
        hw, _ = self.akun()
        t = self.trip(hw)
        it = self.item(hw, t["id"]).json()
        self.assertEqual(self.c.post("/api/host/closed", json={"kegiatan_id": "K01", "tanggal": NANTI},
                                     headers=hh).status_code, 403)  # bukan miliknya
        self.c.post("/api/host/closed", json={"kegiatan_id": "K04", "tanggal": NANTI}, headers=hh)
        self.assertEqual(self.c.get("/api/kegiatan/K04/tutup").json(), [NANTI])
        self.assertEqual(self.c.post(f"/api/trips/{t['id']}/items/{it['id']}/request", headers=hw).status_code, 409)
        self.assertEqual(self.item(hw, t["id"], kid="K04", tgl=NANTI).status_code, 409)
        self.c.post("/api/host/closed", json={"kegiatan_id": "K04", "tanggal": NANTI, "tutup": False}, headers=hh)
        self.assertEqual(self.c.post(f"/api/trips/{t['id']}/items/{it['id']}/request", headers=hw).status_code, 200)

    def test_ditolak_tidak_dikenai_biaya_dan_boleh_ulang(self):
        hh, _ = self.host("H04")
        hw, _ = self.akun()
        t, it = self.ajukan(hw)
        self.c.post(f"/api/host/requests/{it['id']}/decision", json={"setuju": False}, headers=hh)
        s = self.c.get(f"/api/trips/{t['id']}/settlement", headers=hw).json()
        self.assertEqual(s["total"], 0)
        self.assertEqual(self.item(hw, t["id"]).status_code, 201)  # yang ditolak tidak dihitung duplikat


class TesPatungan(Dasar):
    def test_pengeluaran_dan_item_masuk_pelunasan(self):
        h1, u1 = self.akun("Maya")
        t = self.trip(h1)
        h2, u2 = self.akun("Daniel")
        self.c.post("/api/trips/join", json={"kode": t["kode"]}, headers=h2)
        it = self.item(h1, t["id"], jumlah_orang=2).json()   # dibayar bendahara (Maya), dibagi dua
        r = self.c.post(f"/api/trips/{t['id']}/expenses", json={"judul": "Sewa mobil", "jumlah": 1_000_000,
                                                                 "dibayar_oleh": u2["id"],
                                                                 "dibagi_ke": [u1["id"], u2["id"]]}, headers=h2)
        self.assertEqual(r.status_code, 201)
        s = self.c.get(f"/api/trips/{t['id']}/settlement", headers=h1).json()
        self.assertEqual(s["total"], 1_000_000 + it["biaya"])
        selisih = (1_000_000 - it["biaya"]) // 2
        self.assertEqual(s["transfer"], [{"dari_id": u1["id"], "ke_id": u2["id"], "jumlah": selisih,
                                          "dari_nama": "Maya", "ke_nama": "Daniel", "lunas": False}])
        self.c.post(f"/api/trips/{t['id']}/settlement", json={"dari_id": u1["id"], "ke_id": u2["id"]}, headers=h1)
        self.assertTrue(self.c.get(f"/api/trips/{t['id']}/settlement", headers=h1).json()["transfer"][0]["lunas"])

    def test_penanggung_harus_anggota(self):
        h, u = self.akun()
        t = self.trip(h)
        r = self.c.post(f"/api/trips/{t['id']}/expenses", json={"judul": "x", "jumlah": 10, "dibayar_oleh": u["id"],
                                                                 "dibagi_ke": [u["id"], 9999]}, headers=h)
        self.assertEqual(r.status_code, 422)


class TesKalender(Dasar):
    def test_tanggal_dikenal(self):
        r = self.c.get("/api/kalender?dari=2026-10-20&sampai=2027-01-25").json()
        self.assertTrue(r["perkiraan"])
        purnama = [f["tanggal"] for f in r["fase"] if f["fase"] == "purnama"]
        tilem = [f["tanggal"] for f in r["fase"] if f["fase"] == "tilem"]
        # sama dengan daftar di data.js front-end
        self.assertEqual(purnama, ["2026-10-26", "2026-11-24", "2026-12-24", "2027-01-22"])
        self.assertEqual(tilem, ["2026-11-09", "2026-12-09", "2027-01-08"])
        self.assertEqual(r["kegiatan_tutup_purnama_tilem"], ["K01", "K05", "K06", "K12"])

    def test_rentang_tidak_valid(self):
        self.assertEqual(self.c.get("/api/kalender?dari=2026-01-01&sampai=2028-01-01").status_code, 422)
        self.assertEqual(self.c.get("/api/kalender?dari=besok").status_code, 422)

    def test_tutup_saat_purnama_tilem(self):
        h, _ = self.akun()
        t = self.trip(h)
        fase = fase_bulan(date.today() + timedelta(days=10), date.today() + timedelta(days=60))[0]
        r = self.item(h, t["id"], kid="K12", tgl=fase["tanggal"])            # K12 terpengaruh purnama/tilem
        self.assertEqual(r.status_code, 409)
        self.assertIn(fase["fase"], r.json()["detail"])
        self.assertEqual(self.item(h, t["id"], kid="K09", tgl=fase["tanggal"]).status_code, 201)  # K09 tidak

    def test_jam_default_dari_jadwal(self):
        h, _ = self.akun()
        t = self.trip(h)
        self.assertEqual(self.item(h, t["id"], kid="K06").json()["jam"], "19:00")


class TesPlus(Dasar):
    def test_uji_coba_sekali_dan_kuota_naik(self):
        h, _ = self.akun()
        self.assertEqual(self.c.get("/api/auth/me", headers=h).json()["kuota"]["batas"], 5)
        r = self.c.post("/api/akun/plus", json={"uji_coba": True}, headers=h).json()
        self.assertEqual(r["plus_sampai"], (date.today() + timedelta(days=7)).isoformat())
        me = self.c.get("/api/auth/me", headers=h).json()
        self.assertEqual((me["paket"], me["kuota"]["batas"]), ("plus", 200))
        self.assertEqual(self.c.post("/api/akun/plus", json={"uji_coba": True}, headers=h).status_code, 409)
        r = self.c.post("/api/akun/plus", json={}, headers=h).json()  # simulasi bayar: +30 hari dari akhir masa
        self.assertEqual(r["plus_sampai"], (date.today() + timedelta(days=37)).isoformat())


if __name__ == "__main__":
    unittest.main()
