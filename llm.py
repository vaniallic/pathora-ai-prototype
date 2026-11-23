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


def buat_llm_gemini(model=None, api_key=None, maks_token=2048, timeout=90, maks_coba=3, jeda=5):
    """Penghubung ke Gemini lewat REST (hanya pustaka bawaan Python, tanpa pip install).

    Mengulang otomatis kalau timeout, batas laju (429), atau gangguan server (5xx).
    Butuh GEMINI_API_KEY (dari Google AI Studio) di variabel lingkungan. Model bisa diatur lewat
    GEMINI_MODEL. JANGAN simpan kunci di kode atau repo.
    """
    import json
    import time
    import urllib.error
    import urllib.request

    kunci = api_key or os.environ.get("GEMINI_API_KEY")
    if not kunci:
        raise RuntimeError('GEMINI_API_KEY belum diatur. Jalankan: export GEMINI_API_KEY="KUNCI_KAMU"')
    nama_model = model or os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{nama_model}:generateContent"

    def llm(system, user):
        badan = json.dumps({
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": maks_token},
        }).encode("utf-8")
        masalah = ""
        for percobaan in range(maks_coba):
            req = urllib.request.Request(
                url, data=badan, method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": kunci})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.load(r)
            except urllib.error.HTTPError as e:
                isi = e.read().decode("utf-8", "replace")[:300]
                masalah = f"Gemini menolak permintaan (HTTP {e.code}): {isi}"
                if e.code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(masalah)  # salah kunci, salah nama model, dsb: ulang tidak membantu
            except (TimeoutError, urllib.error.URLError, OSError) as e:
                masalah = f"Tidak bisa terhubung ke Gemini atau terlalu lama menunggu ({type(e).__name__}: {e})"
            else:
                kandidat = (data.get("candidates") or [{}])[0]
                bagian = (kandidat.get("content") or {}).get("parts") or []
                teks = "".join(b.get("text", "") for b in bagian)
                if not teks:
                    raise RuntimeError(f"Gemini tidak mengembalikan teks (alasan: {kandidat.get('finishReason', 'tidak diketahui')})")
                return teks
            if percobaan < maks_coba - 1:
                time.sleep(jeda * (percobaan + 1))
        raise RuntimeError(masalah)

    return llm


def buat_llm(penyedia="gemini"):
    if penyedia == "gemini":
        return buat_llm_gemini()
    if penyedia == "anthropic":
        return buat_llm_anthropic()
    raise ValueError(f"penyedia tidak dikenal: {penyedia}")
