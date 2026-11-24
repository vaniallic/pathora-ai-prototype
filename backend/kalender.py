"""Tanggal purnama dan tilem, dihitung secara astronomis.

Purnama = hari bulan penuh, tilem = hari bulan baru, menurut waktu Bali (WITA, UTC+8). Rumus fase bulan dari
Jean Meeus, "Astronomical Algorithms" (2nd ed.), bab 49, dengan ketelitian beberapa menit.

PERKIRAAN: kalender Bali (Saka) menetapkan purnama dan tilem dengan perhitungannya sendiri, dan sesekali bisa
selisih satu hari dari fase astronomis. Sebelum dipakai untuk penawaran resmi, cocokkan dengan kalender Bali
dari sumber yang tepercaya (misalnya PHDI atau kalender Bali cetak).
"""
import math
from datetime import date, datetime, timedelta, timezone

WITA = timezone(timedelta(hours=8))
_J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)


def _jde_fase(k):
    """JDE (Julian Ephemeris Day) fase bulan k. k bulat = bulan baru, k + 0.5 = bulan penuh."""
    t = k / 1236.85
    jde = (2451550.09766 + 29.530588861 * k + 0.00015437 * t ** 2 - 0.000000150 * t ** 3
           + 0.00000000073 * t ** 4)
    e = 1 - 0.002516 * t - 0.0000074 * t ** 2
    r = math.radians
    m = r(2.5534 + 29.10535670 * k - 0.0000014 * t ** 2 - 0.00000011 * t ** 3)          # anomali matahari
    mp = r(201.5643 + 385.81693528 * k + 0.0107582 * t ** 2 + 0.00001238 * t ** 3
           - 0.000000058 * t ** 4)                                                      # anomali bulan
    f = r(160.7108 + 390.67050284 * k - 0.0016118 * t ** 2 - 0.00000227 * t ** 3
          + 0.000000011 * t ** 4)                                                       # argumen lintang
    om = r(124.7746 - 1.56375588 * k + 0.0020672 * t ** 2 + 0.00000215 * t ** 3)        # simpul naik
    baru = abs(k - round(k)) < 1e-9
    if baru:
        kor = (-0.40720 * math.sin(mp) + 0.17241 * e * math.sin(m) + 0.01608 * math.sin(2 * mp)
               + 0.01039 * math.sin(2 * f) + 0.00739 * e * math.sin(mp - m) - 0.00514 * e * math.sin(mp + m)
               + 0.00208 * e * e * math.sin(2 * m))
    else:
        kor = (-0.40614 * math.sin(mp) + 0.17302 * e * math.sin(m) + 0.01614 * math.sin(2 * mp)
               + 0.01043 * math.sin(2 * f) + 0.00734 * e * math.sin(mp - m) - 0.00515 * e * math.sin(mp + m)
               + 0.00209 * e * e * math.sin(2 * m))
    kor += (-0.00111 * math.sin(mp - 2 * f) - 0.00057 * math.sin(mp + 2 * f) + 0.00056 * e * math.sin(2 * mp + m)
            - 0.00042 * math.sin(3 * mp) + 0.00042 * e * math.sin(m + 2 * f) + 0.00038 * e * math.sin(m - 2 * f)
            - 0.00024 * e * math.sin(2 * mp - m) - 0.00017 * math.sin(om) - 0.00007 * math.sin(mp + 2 * m)
            + 0.00004 * math.sin(2 * mp - 2 * f) + 0.00004 * math.sin(3 * m) + 0.00003 * math.sin(mp + m - 2 * f)
            + 0.00003 * math.sin(2 * mp + 2 * f) - 0.00003 * math.sin(mp + m + 2 * f)
            + 0.00003 * math.sin(mp - m + 2 * f) - 0.00002 * math.sin(mp - m - 2 * f)
            - 0.00002 * math.sin(3 * mp + m) + 0.00002 * math.sin(4 * mp))
    # koreksi planet (Meeus tabel 49.b)
    a = [299.77 + 0.107408 * k - 0.009173 * t ** 2, 251.88 + 0.016321 * k, 251.83 + 26.651886 * k,
         349.42 + 36.412478 * k, 84.66 + 18.206239 * k, 141.74 + 53.303771 * k, 207.14 + 2.453732 * k,
         154.84 + 7.306860 * k, 34.52 + 27.261239 * k, 207.19 + 0.121824 * k, 291.34 + 1.844379 * k,
         161.72 + 24.198154 * k, 239.56 + 25.513099 * k, 331.55 + 3.592518 * k]
    koef = [0.000325, 0.000165, 0.000164, 0.000126, 0.000110, 0.000062, 0.000060, 0.000056, 0.000047,
            0.000042, 0.000040, 0.000037, 0.000035, 0.000023]
    kor += sum(c * math.sin(r(x)) for c, x in zip(koef, a))
    return jde + kor


def _ke_tanggal_wita(jde):
    # JDE ~ JD (selisih TT-UT sekitar 70 detik, tidak mengubah tanggal kecuali tepat di tengah malam)
    return (_J2000 + timedelta(days=jde - 2451545.0)).astimezone(WITA)


def fase_bulan(dari, sampai):
    """Daftar {tanggal, fase: 'purnama'|'tilem', waktu_wita} dari `dari` sampai `sampai` (date), urut."""
    k = math.floor((dari.year + (dari.timetuple().tm_yday - 1) / 365.25 - 2000) * 12.3685) - 1
    hasil = []
    while True:
        for kk, nama in ((k, "tilem"), (k + 0.5, "purnama")):
            w = _ke_tanggal_wita(_jde_fase(kk))
            if w.date() > sampai:
                return hasil
            if w.date() >= dari:
                hasil.append({"tanggal": w.date().isoformat(), "fase": nama,
                              "waktu_wita": w.strftime("%Y-%m-%d %H:%M")})
        k += 1


def fase_pada(tanggal):
    """'purnama', 'tilem', atau None untuk satu tanggal (date atau 'YYYY-MM-DD')."""
    t = date.fromisoformat(tanggal) if isinstance(tanggal, str) else tanggal
    for f in fase_bulan(t, t):
        return f["fase"]
    return None
