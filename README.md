# Pathora AI: kerangka penyusun itinerary (hibrida)

Bagian dari proyek kelompok Pathora (Group project). Folder ini berisi kerangka data dan logika, bukan produk jadi.

## Isi

- `load_data.py`: membaca CSV tab Kegiatan dan Host, memeriksa kesiapan tiap kegiatan, menulis JSON ke `out/`.
- `planner.py`: menyusun itinerary dari kegiatan yang sudah siap, memakai aturan (bukan model bahasa).
- `prompts/`: dua prompt untuk model bahasa (memahami permintaan, dan menjelaskan hasil).
- `ekstrak.py`: memanggil model untuk mengubah kalimat wisatawan jadi preferensi, lalu MEMVALIDASI hasilnya (tema harus dari daftar, angka masuk akal, dst).
- `narasi.py`: memanggil model untuk menjelaskan hasil planner, lalu MEMERIKSA (tidak boleh ada harga atau kegiatan yang tidak ada di rencana). Kalau gagal, dipakai teks cadangan dari data.
- `asisten.py`: merangkai semuanya dari permintaan sampai jawaban.
- `llm.py`: penghubung ke API model bahasa (Claude dan Gemini). Kuncinya hanya boleh di server.
- `backend/`: server API (FastAPI + SQLite): daftar akun, login, riwayat, dan endpoint asisten. Lihat bagian Backend di bawah.
- `tests/test_planner.py`: tes logika dengan data CONTOH fiktif (bukan data asli).
- `data/`: salinan CSV dari spreadsheet (Kegiatan, Host, Riset_Destinasi).

## Alur

1. Wisatawan menulis permintaan bebas.
2. Model bahasa mengubahnya jadi JSON preferensi (prompt 1).
3. `planner.py` memilih kegiatan dari data terverifikasi dan menyusun jadwal.
4. Model bahasa menjelaskan hasilnya tanpa menambah informasi (prompt 2).

## Perintah

    python3 -I -m unittest discover -s tests -v
    python3 load_data.py data/Kegiatan.csv data/Host.csv --out out
    python3 planner.py out/kegiatan_siap.json '{"durasi_hari": 2, "tema": ["alam"]}'

Perintah ketiga baru memberi hasil kalau sudah ada kegiatan yang lolos pemeriksaan.

## Syarat sebuah kegiatan boleh direkomendasikan

Status data "Terverifikasi", kolom harga, durasi, kuota, dan tingkat kesulitan terisi, ID Host ada di tab Host, dan host menyatakan setuju tampil ("Ya").

## Belum ada (perlu keputusan tim)

- Data waktu tempuh antar desa. Tanpa ini, kegiatan di desa berbeda tidak digabung dalam satu hari.
- Angka aturan di `ATURAN` (planner.py) adalah asumsi awal untuk diuji.


## Menyambung ke Gemini (gratis untuk demo)

1. Ambil kunci di Google AI Studio (aistudio.google.com), menu "Get API key".
2. Di Terminal (kunci hanya hidup di sesi ini, jangan disimpan di berkas):
   `export GEMINI_API_KEY="KUNCI_KAMU"`
3. Jalankan: `python3 asisten.py "3 hari, suka alam" --data out_demo/kegiatan_siap.json --semua out_demo/kegiatan.json`

Pilihan `--penyedia anthropic` memakai Claude (butuh `pip install anthropic` dan `ANTHROPIC_API_KEY`).
Penghubung Gemini BELUM diuji dengan kunci asli.


## Backend (server API)

Backend memakai FastAPI, database SQLite, dan Claude sebagai model bahasa default.

### Menjalankan

    pip install -r backend/requirements.txt
    cp backend/.env.example backend/.env      # lalu isi ANTHROPIC_API_KEY dan JWT_SECRET
    uvicorn backend.main:app --reload --port 8000

Buka http://localhost:8000/ untuk halaman uji (daftar, login, minta rencana), dan
http://localhost:8000/docs untuk dokumentasi semua endpoint.

Kunci Claude diambil dari console.anthropic.com (menu API Keys), formatnya diawali `sk-ant-`.
Berkas `backend/.env` dan `backend/*.db` sudah ada di `.gitignore`, jadi tidak ikut ter-push.

### Endpoint

| Metode | Alamat | Login? | Fungsi |
|---|---|---|---|
| GET | /api/health | tidak | status server, jumlah kegiatan siap |
| GET | /api/kegiatan | tidak | daftar kegiatan siap (tanpa kontak host) |
| POST | /api/auth/signup | tidak | `{nama, email, password}` -> `{token, pengguna}` |
| POST | /api/auth/login | tidak | `{email, password}` -> `{token, pengguna}` |
| GET | /api/auth/me | ya | data pengguna yang sedang login |
| POST | /api/rencana | ya | `{teks, lanjutan_dari?}` -> `{id, tipe, pesan, prefs?, rencana?}` |
| GET | /api/rencana | ya | riwayat permintaan pengguna |
| GET | /api/rencana/{id} | ya | satu permintaan |
| DELETE | /api/rencana/{id} | ya | hapus permintaan |

Endpoint yang butuh login memakai header `Authorization: Bearer <token>`.

`tipe` bisa `rencana` (itinerary jadi), `tanya` (asisten bertanya balik, misalnya durasi), atau
`galat` (model bermasalah). Kalau `tanya`, kirim jawaban pengguna dengan `lanjutan_dari` berisi `id`
balasan tadi, supaya permintaan awal ikut dibaca.

### Keamanan yang sudah ada

- Password di-hash dengan scrypt (tidak pernah disimpan polos).
- Token login JWT, berlaku 24 jam (atur `TOKEN_BERLAKU_JAM`).
- Login dibatasi 5 kali gagal per 15 menit per email dan IP.
- Pengguna hanya bisa melihat dan menghapus riwayatnya sendiri.
- Kunci API hanya di server. Kalau model gagal, server tidak error 500 tapi membalas `tipe: galat`.

### Tes

    pip install httpx
    python3 -I -m unittest discover -s tests -v
