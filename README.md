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
Penghubung Gemini sudah tersambung dengan kunci asli (25 November 2026). Model Gemini sering penuh (HTTP 503);
karena itu `GEMINI_MODEL` berisi beberapa model cadangan, dan backend punya cadangan berbasis aturan.


## Backend (server API)

Backend memakai FastAPI, database SQLite, dan Gemini sebagai model bahasa default (Claude bisa dipilih
lewat `PENYEDIA_AI=anthropic`).

### Menjalankan

    pip install -r backend/requirements.txt
    cp backend/.env.example backend/.env      # lalu isi GEMINI_API_KEY dan JWT_SECRET
    uvicorn backend.main:app --reload --port 8000

Buka http://localhost:8000/ untuk halaman uji (daftar, login, minta rencana), dan
http://localhost:8000/docs untuk dokumentasi semua endpoint.

Kunci Gemini diambil dari aistudio.google.com (menu Get API key). Kunci Claude dari console.anthropic.com
(menu API Keys), formatnya diawali `sk-ant-`.
Berkas `backend/.env` dan `backend/*.db` sudah ada di `.gitignore`, jadi tidak ikut ter-push.

### Endpoint

| Metode | Alamat | Login? | Fungsi |
|---|---|---|---|
| GET | /api/health | tidak | status server, jumlah kegiatan siap, kuota harian |
| GET | /api/kegiatan | tidak | daftar kegiatan siap, dengan `host_id`, `host_nama`, `lat`, `lng`, `jam_mulai`, `tutup_purnama_tilem` (tanpa kontak host) |
| GET | /api/kalender | tidak | purnama dan tilem `?dari=&sampai=` (perkiraan astronomis, waktu Bali, maks 400 hari) |
| POST | /api/auth/signup | tidak | `{nama, email, password, peran?, komunitas?, tempat?}` -> `{token, pengguna}` |
| POST | /api/auth/login | tidak | `{email, password}` -> `{token, pengguna}` |
| GET | /api/auth/me | ya | pengguna + `kuota: {batas, terpakai, sisa}` |
| POST | /api/rencana | ya | `{teks, lanjutan_dari?, konteks?}` -> `{id, tipe, pesan, prefs?, rencana?}` |
| GET | /api/rencana | ya | riwayat permintaan pengguna |
| GET | /api/rencana/{id} | ya | satu permintaan |
| DELETE | /api/rencana/{id} | ya | hapus permintaan |

Endpoint yang butuh login memakai header `Authorization: Bearer <token>`.

**Akun.** `peran` bernilai `wisatawan` (default) atau `host`; host wajib mengisi `komunitas`. `pengguna` di
respons berisi `id, nama, email, dibuat, peran, komunitas, tempat, paket` (`paket`: `gratis` atau `plus`,
tidak bisa diatur sendiri lewat signup).

**Rencana.** `tipe` selalu salah satu dari `rencana`, `tanya`, `galat`. Kalau `tanya`, kirim jawaban pengguna
dengan `lanjutan_dari` berisi `id` balasan tadi. Setiap `rencana.hari[].kegiatan[].id` adalah ID sheet (K01, K02, ...).
`konteks` opsional: `{tanggal_mulai, tanggal_akhir, jumlah_orang, kegiatan_dipilih}`. Isinya hanya petunjuk:
yang disebut di `teks` selalu menang, nilai yang tidak masuk akal diabaikan, dan kegiatan di `kegiatan_dipilih`
tidak ditawarkan lagi.

**Waktu jawab.** Backend menjawab dalam `AI_BATAS_DETIK` (default 7 detik). Kalau model bahasa lambat atau sibuk,
permintaan dipahami lewat kata kunci dan penjelasan disusun dari data, jadi tetap ada rencana.

**Kuota.** Paket gratis 5 pertanyaan AI per hari (reset tengah malam WIB), Plus 200. Setiap respons
`/api/rencana` membawa header `X-Kuota-Batas` dan `X-Kuota-Sisa`. Jawaban `galat` tidak memotong kuota, dan
menghapus riwayat tidak mengembalikan kuota.

### Pemesanan (P2)

Alur: wisatawan menyusun trip -> mengajukan kegiatan ke host -> host menyetujui atau menolak -> wisatawan membayar
(simulasi) -> host memberi kode hadir -> wisatawan mendapat stempel Paspor Alam. Semua pembayaran adalah SIMULASI.

| Metode | Alamat | Fungsi |
|---|---|---|
| POST | /api/trips | buat trip `{nama, tanggal_mulai, tanggal_akhir}`; pembuat jadi bendahara |
| GET | /api/trips | trip yang saya ikuti |
| GET / PATCH | /api/trips/{id} | detail (anggota, items, acara, pengeluaran) / ubah nama, tanggal, bendahara |
| POST | /api/trips/join | gabung dengan `{kode}` undangan |
| PUT | /api/trips/{id}/saya | `{hari_sibuk: [tanggal]}` |
| POST / DELETE | /api/trips/{id}/items[/{item}] | tambah item `{kegiatan_id, tanggal, jam?, jumlah_orang?}` (jam kosong: jam mulai pertama kegiatan) / hapus (selain disetujui/lunas) |
| POST | /api/trips/{id}/items/{item}/request | ajukan item draft ke host |
| POST / DELETE | /api/trips/{id}/events[/{acara}] | acara pribadi di kalender |
| POST / DELETE | /api/trips/{id}/expenses[/{id}] | pengeluaran `{judul, jumlah, dibayar_oleh, dibagi_ke, kategori?}` |
| GET / POST | /api/trips/{id}/settlement | saldo dan transfer pelunasan / tandai `{dari_id, ke_id, lunas}` |
| POST | /api/trips/{id}/pay | bayar (simulasi) item disetujui -> lunas, payout dicatat |
| GET | /api/host/kegiatan | kegiatan yang dikelola akun host dan hari tutupnya |
| POST | /api/host/klaim | (mode demo) akun host mengklaim ID host sheet, misalnya `{host_id: "H04"}` |
| POST | /api/admin/host | (admin, `ADMIN_EMAILS`) tetapkan akun host ke ID host |
| GET | /api/host/requests | permintaan masuk (nama pendek pengaju, tanpa email), terisi sesi, kode hadir |
| POST | /api/host/requests/{item}/decision | `{setuju: true/false}`, hanya host pemilik, cek kuota sesi |
| POST | /api/host/closed | `{kegiatan_id, tanggal, tutup}` |
| GET | /api/kegiatan/{id}/tutup | tanggal tutup kegiatan (publik) |
| GET | /api/host/payouts | payout host (simulasi) |
| GET / POST | /api/passport[/stamp] | stempel saya / klaim stempel dengan `{kode}` hadir |
| POST | /api/akun/plus | (simulasi) `{uji_coba: true}` 7 hari sekali per akun, atau +30 hari |

Hari tutup: tanggal yang ditutup host, dan purnama/tilem untuk kegiatan bertanda `tutup_purnama_tilem`
(K01, K05, K06, K12 menurut data contoh). Tanggal purnama/tilem dihitung astronomis (Meeus, waktu Bali) dan
bisa selisih satu hari dari kalender Bali; cocokkan dengan kalender resmi sebelum dipakai untuk penawaran resmi.
Lokasi, jam mulai, dan tanda purnama/tilem ada di `data/lokasi_jadwal.csv` (CONTOH, disalin dari front-end).

Aturan: status item `draft -> diajukan -> disetujui | ditolak`, lalu `disetujui -> lunas`. Bayar hanya setelah
disetujui; item ditolak tidak dihitung biaya. Kuota per sesi (kegiatan + tanggal + jam). Kegiatan yang sama di
tanggal yang sama tidak boleh dua kali dalam satu trip. Biaya = harga per orang x jumlah orang dari data. Item kegiatan
otomatis masuk patungan sebagai pengeluaran yang dibayar bendahara. Kegiatan memakai ID sheet (K01, ...).

**Galat.** Semua galat berbentuk `{"detail": "<teks>"}`.

| Status | Arti |
|---|---|
| 401 | token tidak ada, tidak sah, atau habis |
| 404 | data tidak ditemukan |
| 403 | bukan akun host, atau kegiatan bukan milik host ini |
| 409 | email sudah terdaftar, duplikat, hari tutup, kuota sesi penuh, atau status item tidak sesuai |
| 422 | isian tidak valid (pesan menyebut kolomnya) |
| 429 | kuota harian habis, terlalu banyak percobaan login, atau terlalu banyak permintaan; ada header `Retry-After` (detik) |
| 500 | kegagalan server sungguhan |

### Keamanan yang sudah ada

- Password di-hash dengan scrypt (tidak pernah disimpan polos).
- Token login JWT, berlaku 24 jam (atur `TOKEN_BERLAKU_JAM`).
- Login dibatasi 5 kali gagal per 15 menit per email dan IP; pendaftaran 10 per jam per IP;
  `/api/rencana` 20 per menit per IP (di luar kuota harian per akun).
- Pengguna hanya bisa melihat dan menghapus riwayatnya sendiri.
- Kunci API hanya di server. Kalau model gagal, server tidak error 500 tapi membalas `tipe: galat`.

### Tes

    pip install httpx
    python3 -I -m unittest discover -s tests -v


## Deploy

Backend tidak bisa di Netlify (khusus situs statis). Berkas `Dockerfile` sudah siap untuk hosting berbasis Docker.

Yang wajib, di hosting mana pun:

1. **Volume persisten** dipasang di `/data`. Database ada di `/data/pathora.db`; tanpa volume, semua akun hilang
   setiap server restart.
2. **Variabel lingkungan**:
   - `JWT_SECRET`: acak dan panjang (`python -c "import secrets; print(secrets.token_urlsafe(48))"`)
   - `PENYEDIA_AI=gemini` dan `GEMINI_API_KEY` (atau `anthropic` dan `ANTHROPIC_API_KEY`)
   - `GEMINI_MODEL=gemini-3.8-flash,gemini-3.1-flash-lite`
   - `CORS_ORIGINS=https://pathoraweb.netlify.app,http://localhost:5173`
   - `PATHORA_DEMO=1` selama data belum terverifikasi
3. **HTTPS**: domain bawaan hosting sudah HTTPS.
4. Cek dari browser: `https://<alamat-backend>/api/health` harus membalas `"status":"ok"`.

### Railway (disarankan untuk prototype)

Paket Free Railway tidak butuh kartu kredit dan menyediakan 1 volume 0,5 GB. Layanan tidur saat sepi, jadi
permintaan pertama setelah tidur bisa lambat; front-end memakai mesin lokal kalau lewat 8 detik.

1. Di railway.com: New Project -> Deploy from GitHub repo -> pilih repo ini. Railway membaca `Dockerfile`.
2. Klik layanan -> Variables: isi variabel di atas.
3. Klik kanan layanan -> Attach volume, mount path `/data`.
4. Settings -> Networking -> Generate Domain. Alamat itu yang diberikan ke front-end (`window.PATHORA_API_BASE`).

### Render

Paket gratis Render tidak punya disk persisten dan Postgres gratisnya kedaluwarsa setelah 30 hari, jadi butuh
paket berbayar dengan disk yang dipasang di `/data`.
