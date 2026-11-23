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


def buat_llm_gemini(model=None, api_key=None, maks_token=2048, timeout=30):
    """Penghubung ke Gemini lewat REST (hanya pustaka bawaan Python, tanpa pip install).

    BELUM DIUJI dengan kunci asli. Butuh GEMINI_API_KEY (dari Google AI Studio) di variabel
    lingkungan. Model bisa diatur lewat GEMINI_MODEL. JANGAN simpan kunci di kode atau repo.
    """
    import json
    import urllib.error
    import urllib.request

    kunci = api_key or os.environ.get("GEMINI_API_KEY")
    if not kunci:
        raise RuntimeError('GEMINI_API_KEY belum diatur. Jalankan: export GEMINI_API_KEY="KUNCI_KAMU"')
    nama_model = model or os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{nama_model}:generateContent"

    def llm(system, user):
        badan = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": maks_token},
        }
        req = urllib.request.Request(
            url, data=json.dumps(badan).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": kunci}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Gemini menolak permintaan (HTTP {e.code}): {e.read().decode('utf-8', 'replace')[:300]}")
        kandidat = (data.get("candidates") or [{}])[0]
        bagian = (kandidat.get("content") or {}).get("parts") or []
        teks = "".join(b.get("text", "") for b in bagian)
        if not teks:
            raise RuntimeError(f"Gemini tidak mengembalikan teks (alasan: {kandidat.get('finishReason', 'tidak diketahui')})")
        return teks

    return llm


def buat_llm(penyedia="gemini"):
    if penyedia == "gemini":
        return buat_llm_gemini()
    if penyedia == "anthropic":
        return buat_llm_anthropic()
    raise ValueError(f"penyedia tidak dikenal: {penyedia}")
