# Pathora AI: kerangka penyusun itinerary (hibrida)

Bagian dari proyek kelompok Pathora (Group project). Folder ini berisi kerangka data dan logika, bukan produk jadi.

## Isi

- `load_data.py`: membaca CSV tab Kegiatan dan Host, memeriksa kesiapan tiap kegiatan, menulis JSON ke `out/`.
- `planner.py`: menyusun itinerary dari kegiatan yang sudah siap, memakai aturan (bukan model bahasa).
- `prompts/`: dua prompt untuk model bahasa (memahami permintaan, dan menjelaskan hasil).
- `ekstrak.py`: memanggil model untuk mengubah kalimat wisatawan jadi preferensi, lalu MEMVALIDASI hasilnya (tema harus dari daftar, angka masuk akal, dst).
- `narasi.py`: memanggil model untuk menjelaskan hasil planner, lalu MEMERIKSA (tidak boleh ada harga atau kegiatan yang tidak ada di rencana). Kalau gagal, dipakai teks cadangan dari data.
- `asisten.py`: merangkai semuanya dari permintaan sampai jawaban.
- `llm.py`: penghubung ke API model bahasa. BELUM DIUJI dengan kunci asli, dan kuncinya hanya boleh di server.
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
- Pemanggilan API model bahasa. Kunci API harus disimpan di backend, bukan di front-end.
- Angka aturan di `ATURAN` (planner.py) adalah asumsi awal untuk diuji.


## Menyambung ke Gemini (gratis untuk demo)

1. Ambil kunci di Google AI Studio (aistudio.google.com), menu "Get API key".
2. Di Terminal (kunci hanya hidup di sesi ini, jangan disimpan di berkas):
   `export GEMINI_API_KEY="KUNCI_KAMU"`
3. Jalankan: `python3 asisten.py "3 hari, suka alam" --data out_demo/kegiatan_siap.json --semua out_demo/kegiatan.json`

Pilihan `--penyedia anthropic` memakai Claude (butuh `pip install anthropic` dan `ANTHROPIC_API_KEY`).
Penghubung Gemini BELUM diuji dengan kunci asli.
