"""Konfigurasi client-bot + loader .env (tanpa dependency tambahan)."""
import os
import platform


def load_env(path=".env"):
    """Parse file .env sederhana -> dict, juga inject ke os.environ."""
    env = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                env[k] = v
                os.environ.setdefault(k, v)
    return env


ENV = load_env()


def _flag(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on", "y")


# --- Koneksi ke master-bot (socket) ---
# Alamat & port broadcaster master (signal_broadcaster.py).
MASTER_HOST = ENV.get("MASTER_HOST", "127.0.0.1")
MASTER_PORT = int(ENV.get("MASTER_PORT", "9009"))
# Jeda reconnect (detik): mulai dari min, naik bertahap sampai max (backoff).
RECONNECT_MIN = float(ENV.get("RECONNECT_MIN", "2"))
RECONNECT_MAX = float(ENV.get("RECONNECT_MAX", "30"))
# Socket dianggap mati jika diam (tanpa heartbeat) > SOCKET_TIMEOUT detik.
SOCKET_TIMEOUT = float(ENV.get("SOCKET_TIMEOUT", "45"))

# --- MT5 (eksekusi order, KHUSUS Windows + terminal MetaTrader 5) ---
MT5_SYMBOL = ENV.get("MT5_SYMBOL", "XAUUSD")     # nama simbol di broker client
MT5_LOGIN = ENV.get("MT5_LOGIN", "")             # opsional (login otomatis)
MT5_PASSWORD = ENV.get("MT5_PASSWORD", "")       # opsional
MT5_SERVER = ENV.get("MT5_SERVER", "")           # opsional
MT5_PATH = ENV.get("MT5_PATH", "")               # opsional: path terminal64.exe

# --- Parameter eksekusi order ---
TRADE_LOT = float(ENV.get("TRADE_LOT", "0.1"))            # ukuran lot per posisi
TRADE_MAGIC = int(ENV.get("TRADE_MAGIC", "640064"))       # magic number bot
TRADE_DEVIATION = int(ENV.get("TRADE_DEVIATION", "20"))   # slippage maks (points)
MAX_OPEN_POSITIONS = int(ENV.get("MAX_OPEN_POSITIONS", "1"))  # batas posisi aktif
# Mode filling: auto (deteksi dari simbol) | ioc | fok | return
TRADE_FILLING = ENV.get("TRADE_FILLING", "auto").strip().lower()

# Sumber harga TP/SL:
#   0 (default) -> hitung ulang dari JARAK (tp_dist/sl_dist) memakai tick broker
#                  client sendiri. Lebih aman bila feed master & client beda.
#   1           -> pakai harga absolut TP/SL apa adanya dari master.
USE_MASTER_PRICES = _flag(ENV.get("USE_MASTER_PRICES", "0"))

# Dry-run: hanya cetak rencana order, TIDAK eksekusi. Otomatis aktif bila MT5
# tidak tersedia (mis. di macOS/Linux). Set DRY_RUN=1 utk paksa simulasi.
DRY_RUN = _flag(ENV.get("DRY_RUN", "0"))

# Anti-duplikat: abaikan sinyal dengan id sama yg diterima < DEDUP_TTL detik lalu.
DEDUP_TTL = float(ENV.get("DEDUP_TTL", "3600"))

# --- Notifikasi Telegram (opsional; kirim saat order dieksekusi/gagal) ---
TELEGRAM_BOT_TOKEN = ENV.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = ENV.get("TELEGRAM_CHAT_ID", "")

IS_WINDOWS = platform.system() == "Windows"
