"""Penghubung ke API model bahasa.

BELUM DIUJI: kode ini belum pernah dijalankan dengan kunci API asli. Uji dulu di server/backend.
Aturan penting: kunci API hanya boleh ada di server (variabel lingkungan), JANGAN di kode front-end.

Butuh: pip install anthropic, lalu atur ANTHROPIC_API_KEY dan ANTHROPIC_MODEL
(nama model dipilih tim, lihat dokumentasi resmi untuk nama yang tersedia).
"""
import os


def buat_llm_anthropic(model=None, api_key=None, maks_token=1024):
    import anthropic  # diimpor di sini supaya bagian lain tetap bisa dites tanpa paketnya

    client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
    nama_model = model or os.environ["ANTHROPIC_MODEL"]

    def llm(system, user):
        r = client.messages.create(
            model=nama_model, max_tokens=maks_token, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")

    return llm
