"""Penghubung ke API model bahasa.

Aturan penting: kunci API hanya boleh ada di server (variabel lingkungan), JANGAN di kode front-end.

Claude: pip install anthropic, lalu atur ANTHROPIC_API_KEY (dan opsional ANTHROPIC_MODEL,
default claude-sonnet-5-5). Backend (backend/) memakai Claude secara default.
"""
import os


MODEL_ANTHROPIC_DEFAULT = "claude-sonnet-5-5"


def buat_llm_anthropic(model=None, api_key=None, maks_token=1024, timeout=60, maks_coba=2, sisa_waktu=None):
    """Penghubung ke Claude (Anthropic). Kunci dibaca dari ANTHROPIC_API_KEY di server.

    Semua galat dari API diubah jadi RuntimeError, supaya asisten.py bisa jatuh ke teks cadangan
    alih-alih membuat server error 500.
    """
    import anthropic  # diimpor di sini supaya bagian lain tetap bisa dites tanpa paketnya

    kunci = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not kunci:
        raise RuntimeError("ANTHROPIC_API_KEY belum diatur (isi di berkas .env di server).")
    client = anthropic.Anthropic(api_key=kunci, timeout=timeout, max_retries=maks_coba)
    nama_model = model or os.environ.get("ANTHROPIC_MODEL") or MODEL_ANTHROPIC_DEFAULT

    def llm(system, user):
        batas = timeout
        if sisa_waktu is not None:
            batas = min(timeout, sisa_waktu())
            if batas < 1:
                raise RuntimeError("batas waktu habis sebelum Claude sempat menjawab")
        try:
            r = client.messages.create(
                model=nama_model, max_tokens=maks_token, system=system,
                messages=[{"role": "user", "content": user}], timeout=batas,
            )
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Claude menolak permintaan (HTTP {e.status_code}): {str(e)[:300]}") from e
        except anthropic.APIError as e:
            raise RuntimeError(f"Tidak bisa terhubung ke Claude ({type(e).__name__}: {e})") from e
        teks = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        if not teks:
            raise RuntimeError(f"Claude tidak mengembalikan teks (stop_reason: {r.stop_reason})")
        return teks

    return llm


def buat_llm_gemini(model=None, api_key=None, maks_token=2048, timeout=40, maks_coba=2, jeda=3, sisa_waktu=None):
    """Penghubung ke Gemini lewat REST (hanya pustaka bawaan Python, tanpa pip install).

    Mengulang otomatis kalau timeout, batas laju (429), atau gangguan server (5xx).
    GEMINI_MODEL boleh berisi beberapa model dipisah koma, misalnya
    "gemini-3.8-flash,gemini-3.1-flash-lite". Kalau model pertama terus sibuk (503/429) atau
    sudah tidak tersedia (404),
    model berikutnya dicoba. sisa_waktu (opsional): fungsi yang mengembalikan sisa detik yang boleh dipakai;
    kalau habis, pemanggilan berhenti dan galat dilempar supaya pemanggil memakai cadangan.
    Butuh GEMINI_API_KEY di variabel lingkungan. JANGAN simpan kunci di kode atau repo.
    """
    import json
    import time
    import urllib.error
    import urllib.request

    kunci = api_key or os.environ.get("GEMINI_API_KEY")
    if not kunci:
        raise RuntimeError('GEMINI_API_KEY belum diatur. Isi di backend/.env atau jalankan: export GEMINI_API_KEY="KUNCI_KAMU"')
    daftar = model or os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash,gemini-3.1-flash-lite"
    daftar_model = [m.strip() for m in daftar.split(",") if m.strip()]

    def _panggil(nama_model, badan):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{nama_model}:generateContent"
        masalah = ""
        for percobaan in range(maks_coba):
            batas = timeout
            if sisa_waktu is not None:
                sisa = sisa_waktu()
                if sisa < 1:
                    raise _Sibuk(masalah or "batas waktu habis sebelum Gemini sempat menjawab")
                batas = min(timeout, sisa)
            req = urllib.request.Request(
                url, data=badan, method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": kunci})
            try:
                with urllib.request.urlopen(req, timeout=batas) as r:
                    data = json.load(r)
            except urllib.error.HTTPError as e:
                isi = e.read().decode("utf-8", "replace")[:300]
                masalah = f"Gemini ({nama_model}) menolak permintaan (HTTP {e.code}): {isi}"
                if e.code == 404:
                    raise _Sibuk(masalah)  # model sudah tidak tersedia: langsung coba model berikutnya
                if e.code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(masalah)  # salah kunci dsb: ulang tidak membantu
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
                tunggu = jeda * (percobaan + 1)
                if sisa_waktu is not None and sisa_waktu() < tunggu + 1:
                    break  # tidak cukup waktu untuk mencoba lagi
                time.sleep(tunggu)
        raise _Sibuk(masalah)

    def llm(system, user):
        badan = json.dumps({
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": maks_token},
        }).encode("utf-8")
        masalah = []
        for nama_model in daftar_model:
            try:
                return _panggil(nama_model, badan)
            except _Sibuk as e:
                masalah.append(str(e))  # model ini sibuk: coba model berikutnya
        raise RuntimeError(" | ".join(masalah))

    return llm


class _Sibuk(RuntimeError):
    """Model sibuk atau tidak terjangkau setelah beberapa percobaan."""


def buat_llm(penyedia="gemini", **opsi):
    """opsi diteruskan ke penghubung, misalnya sisa_waktu=... (dipakai backend)."""
    if penyedia == "gemini":
        return buat_llm_gemini(**opsi)
    if penyedia == "anthropic":
        return buat_llm_anthropic(**opsi)
    raise ValueError(f"penyedia tidak dikenal: {penyedia}")
