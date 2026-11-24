"""Hash password (scrypt, pustaka bawaan Python), token JWT, dan pembatas percobaan login."""
import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt

_N, _R, _P = 2**14, 8, 1


def hash_password(password):
    garam = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=garam, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}".format(base64.b64encode(garam).decode(), base64.b64encode(h).decode())


def cek_password(password, tersimpan):
    try:
        algo, garam, h = tersimpan.split("$")
        if algo != "scrypt":
            return False
        hitung = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(garam), n=_N, r=_R, p=_P, dklen=32)
        return hmac.compare_digest(hitung, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


# Hash palsu: dipakai saat email tidak ada, supaya waktu respons sama (tidak membocorkan email terdaftar).
HASH_PALSU = hash_password(secrets.token_urlsafe(16))


def buat_token(pengguna_id, rahasia, berlaku_jam):
    sekarang = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(pengguna_id), "iat": sekarang, "exp": sekarang + timedelta(hours=berlaku_jam)},
                      rahasia, algorithm="HS256")


def baca_token(token, rahasia):
    """Mengembalikan id pengguna (int), atau None kalau token tidak sah atau kedaluwarsa."""
    try:
        return int(jwt.decode(token, rahasia, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


class PembatasLogin:
    """Maksimal `maks` percobaan gagal per kunci (email + IP) dalam `jendela` detik."""

    def __init__(self, maks=5, jendela=15 * 60):
        self.maks, self.jendela = maks, jendela
        self.gagal = defaultdict(deque)

    def _bersihkan(self, kunci):
        q = self.gagal[kunci]
        while q and q[0] < time.monotonic() - self.jendela:
            q.popleft()
        return q

    def diblokir(self, kunci):
        return len(self._bersihkan(kunci)) >= self.maks

    def catat_gagal(self, kunci):
        self._bersihkan(kunci).append(time.monotonic())

    def reset(self, kunci):
        self.gagal.pop(kunci, None)


class PembatasLaju:
    """Maksimal `maks` permintaan per kunci (misalnya IP) dalam `jendela` detik."""

    def __init__(self, maks, jendela):
        self.maks, self.jendela = maks, jendela
        self.catatan = defaultdict(deque)

    def coba(self, kunci):
        """Mengembalikan 0 kalau boleh (dan mencatatnya), atau detik yang perlu ditunggu."""
        sekarang = time.monotonic()
        q = self.catatan[kunci]
        while q and q[0] <= sekarang - self.jendela:
            q.popleft()
        if len(q) >= self.maks:
            return max(1, int(q[0] + self.jendela - sekarang) + 1)
        q.append(sekarang)
        return 0
