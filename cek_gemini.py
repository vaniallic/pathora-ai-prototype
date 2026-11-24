"""Tes cepat sambungan ke Gemini: kirim satu kalimat pendek, cetak balasan dan lama tunggu.

Pakai (dari folder repo): python3 cek_gemini.py
Kunci dibaca dari backend/.env atau variabel lingkungan GEMINI_API_KEY.
"""
import time

import backend.config  # noqa: F401  (membaca backend/.env kalau ada)
from llm import buat_llm_gemini

mulai = time.time()
balasan = buat_llm_gemini()("Balas satu kata saja.", "Katakan: siap")
print(f"Balasan Gemini: {balasan.strip()!r} (waktu {time.time() - mulai:.1f} detik)")
