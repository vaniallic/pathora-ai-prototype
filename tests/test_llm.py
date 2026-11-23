"""Tes penghubung Gemini TANPA internet: permintaan ke Google dipalsukan."""
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import llm  # noqa: E402


def _balasan(obj):
    return io.BytesIO(json.dumps(obj).encode("utf-8"))


class TesGemini(unittest.TestCase):
    def test_mengambil_teks_dan_mengirim_kunci_di_header(self):
        palsu = _balasan({"candidates": [{"content": {"parts": [{"text": "Halo "}, {"text": "dunia"}]}}]})
        with mock.patch("urllib.request.urlopen", return_value=palsu) as m:
            f = llm.buat_llm_gemini(api_key="KUNCI-PALSU", model="model-x")
            self.assertEqual(f("sistem", "pengguna"), "Halo dunia")
        req = m.call_args[0][0]
        self.assertEqual(req.get_header("X-goog-api-key"), "KUNCI-PALSU")
        self.assertNotIn("KUNCI-PALSU", req.full_url)  # kunci tidak boleh ada di URL
        self.assertIn("model-x:generateContent", req.full_url)
        badan = json.loads(req.data)
        self.assertEqual(badan["system_instruction"]["parts"][0]["text"], "sistem")

    def test_balasan_kosong_jadi_error_jelas(self):
        palsu = _balasan({"candidates": [{"finishReason": "SAFETY"}]})
        with mock.patch("urllib.request.urlopen", return_value=palsu):
            f = llm.buat_llm_gemini(api_key="k", model="m")
            with self.assertRaises(RuntimeError) as c:
                f("s", "u")
        self.assertIn("SAFETY", str(c.exception))

    def test_http_429_diulang_lalu_error_jelas(self):
        def err():
            return urllib.error.HTTPError("u", 429, "Too Many", {}, io.BytesIO(b"kuota habis"))
        with mock.patch("urllib.request.urlopen", side_effect=[err(), err(), err()]) as m, \
                mock.patch("time.sleep"):
            f = llm.buat_llm_gemini(api_key="k", model="m")
            with self.assertRaises(RuntimeError) as c:
                f("s", "u")
        self.assertIn("429", str(c.exception))
        self.assertEqual(m.call_count, 3)

    def test_salah_kunci_tidak_diulang(self):
        err = urllib.error.HTTPError("u", 400, "Bad", {}, io.BytesIO(b"API key not valid"))
        with mock.patch("urllib.request.urlopen", side_effect=err) as m, mock.patch("time.sleep"):
            f = llm.buat_llm_gemini(api_key="k", model="m")
            with self.assertRaises(RuntimeError):
                f("s", "u")
        self.assertEqual(m.call_count, 1)

    def test_timeout_diulang_lalu_berhasil(self):
        ok = _balasan({"candidates": [{"content": {"parts": [{"text": "Berhasil"}]}}]})
        with mock.patch("urllib.request.urlopen", side_effect=[TimeoutError("read timed out"), ok]) as m, \
                mock.patch("time.sleep"):
            f = llm.buat_llm_gemini(api_key="k", model="m")
            self.assertEqual(f("s", "u"), "Berhasil")
        self.assertEqual(m.call_count, 2)

    def test_timeout_terus_menerus_jadi_runtime_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("read timed out")), \
                mock.patch("time.sleep"):
            f = llm.buat_llm_gemini(api_key="k", model="m")
            with self.assertRaises(RuntimeError) as c:
                f("s", "u")
        self.assertIn("TimeoutError", str(c.exception))

    def test_penyedia_tidak_dikenal(self):
        with self.assertRaises(ValueError):
            llm.buat_llm("lainnya")


if __name__ == "__main__":
    unittest.main()
