"""Tes cepat sambungan ke Gemini: kirim satu kalimat pendek, cetak balasan dan lama tunggu.

Pakai: python3 cek_gemini.py
"""
import time

from llm import buat_llm_gemini

mulai = time.time()
balasan = buat_llm_gemini()("Balas satu kata saja.", "Katakan: siap")
print(f"Balasan Gemini: {balasan.strip()!r} (waktu {time.time() - mulai:.1f} detik)")
