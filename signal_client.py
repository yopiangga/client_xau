"""client-bot: terima sinyal dari master via socket -> eksekusi di MT5 (realtime).

Alur:
  1. Konek ke broadcaster master (signal_broadcaster.py) lewat TCP socket.
  2. Terima pesan NDJSON (newline-delimited JSON) secara realtime.
  3. Untuk tiap pesan type="signal", buka posisi BUY/SELL di MT5 (TP/SL).
  4. Reconnect otomatis (backoff) bila koneksi putus. Heartbeat utk deteksi mati.

Cara pakai:
  python signal_client.py                 # konek ke MASTER_HOST:MASTER_PORT (.env)
  python signal_client.py --host 1.2.3.4 --port 9009
  python signal_client.py --dry-run       # paksa simulasi (tidak buka order)

Di Windows + MetaTrader5 terpasang -> order betulan dikirim ke broker.
Di macOS/Linux (atau --dry-run) -> hanya cetak rencana order (uji koneksi).

PERINGATAN: order memakai dana sungguhan jika akun live. Uji di akun DEMO dulu!
"""
import argparse
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import datetime as dt

import config
import mt5_executor as ex


# ---------- Notifikasi Telegram (opsional) ----------
def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def send_telegram(text):
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10,
                                    context=_ssl_context()) as r:
            r.read()
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLError):
            try:
                with urllib.request.urlopen(
                    url, data=data, timeout=10,
                    context=ssl._create_unverified_context()) as r:
                    r.read()
            except Exception as e2:
                print(f"  [warn] kirim telegram gagal: {e2}")
        else:
            print(f"  [warn] kirim telegram gagal: {e}")
    except Exception as e:
        print(f"  [warn] kirim telegram gagal: {e}")


def _now():
    return dt.datetime.now().strftime("%H:%M:%S")


class Dedup:
    """Cegah eksekusi sinyal ganda (id sama) dalam jendela DEDUP_TTL detik."""

    def __init__(self, ttl):
        self.ttl = ttl
        self.seen = {}

    def is_dup(self, sig_id):
        now = time.time()
        # bersihkan entri lama
        for k in [k for k, t in self.seen.items() if now - t > self.ttl]:
            del self.seen[k]
        if sig_id in self.seen:
            return True
        self.seen[sig_id] = now
        return False


def handle_signal(sig, dry_run, dedup):
    """Proses satu sinyal: validasi, dedup, lalu eksekusi (atau simulasi)."""
    sig_id = sig.get("id") or f"{sig.get('candle')}|{sig.get('side')}"
    side = (sig.get("side") or "").upper()
    if side not in ("BUY", "SELL"):
        print(f"[{_now()}] [skip] sinyal tak dikenal: {sig}")
        return
    if dedup.is_dup(sig_id):
        print(f"[{_now()}] [skip] duplikat sinyal {sig_id}")
        return

    conf = sig.get("confidence", 0) or 0
    sym = config.MT5_SYMBOL
    entry, tp, sl = ex.resolve_prices(sig)
    head = (f"{side} {sym} @~{entry} | TP {tp} | SL {sl} "
            f"| yakin {conf*100:.0f}% | candle {sig.get('candle')}")
    print(f"[{_now()}] 🔔 SINYAL: {head}")

    if dry_run:
        print(f"[{_now()}] [dry-run] TIDAK eksekusi (simulasi saja).")
        send_telegram(f"🧪 [DRY-RUN] {head}")
        return

    # Batas posisi terbuka (mirip master).
    open_count = ex.count_open_positions()
    if open_count >= config.MAX_OPEN_POSITIONS:
        print(f"[{_now()}] [trade] lewati: sudah {open_count} posisi terbuka "
              f"(maks {config.MAX_OPEN_POSITIONS}).")
        return

    result, err = ex.open_position(sig)
    if err:
        print(f"[{_now()}] [trade] GAGAL: {err}")
        send_telegram(f"⚠️ Client GAGAL {side} {sym}: {err}")
        return
    vol = getattr(result, "volume", config.TRADE_LOT)
    px = getattr(result, "price", entry)
    ticket = getattr(result, "order", "?")
    print(f"[{_now()}] [trade] ✅ OPEN {side} {vol} lot @ {px} (ticket {ticket})")
    send_telegram(
        f"✅ CLIENT OPEN {sym} {side} {vol} lot @ {px:.2f}\n"
        f"TP {tp:.2f} | SL {sl:.2f} | yakin {conf*100:.0f}% | ticket {ticket}"
    )


def recv_lines(sock):
    """Generator: yield satu baris (str) tiap pesan NDJSON dari socket."""
    buffer = b""
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            raise                      # diam terlalu lama -> dianggap putus
        if not chunk:
            return                     # peer menutup koneksi
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.strip()
            if line:
                yield line.decode("utf-8", errors="replace")


def listen_once(host, port, dry_run, dedup):
    """Satu sesi koneksi: konek, baca sinyal sampai putus. Return saat putus."""
    sock = socket.create_connection((host, port), timeout=10)
    sock.settimeout(config.SOCKET_TIMEOUT)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"[{_now()}] ✅ tersambung ke master {host}:{port}")
    send_telegram(f"🔌 client-bot tersambung ke master {host}:{port} "
                  f"({'DRY-RUN' if dry_run else 'LIVE'})")
    try:
        for line in recv_lines(sock):
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"[{_now()}] [warn] pesan bukan JSON: {line[:120]}")
                continue
            mtype = msg.get("type")
            if mtype == "signal":
                handle_signal(msg, dry_run, dedup)
            elif mtype == "hello":
                print(f"[{_now()}] hello dari master (symbol {msg.get('symbol')})")
            elif mtype == "heartbeat":
                pass                   # keepalive, abaikan
            else:
                print(f"[{_now()}] [info] pesan: {msg}")
    finally:
        try:
            sock.close()
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser(description="client-bot: terima sinyal master via socket")
    ap.add_argument("--host", default=config.MASTER_HOST)
    ap.add_argument("--port", type=int, default=config.MASTER_PORT)
    ap.add_argument("--dry-run", action="store_true",
                    help="paksa simulasi (tidak buka order)")
    args = ap.parse_args()

    # Dry-run otomatis bila MT5 tidak tersedia (mis. macOS/Linux) atau diset.
    dry_run = args.dry_run or config.DRY_RUN or not ex.is_available()

    print("=" * 60)
    print(f"  CLIENT-BOT (eksekusi MT5)")
    print(f"  master  : {args.host}:{args.port}")
    print(f"  simbol  : {config.MT5_SYMBOL} | lot {config.TRADE_LOT} | "
          f"maks {config.MAX_OPEN_POSITIONS} posisi | magic {config.TRADE_MAGIC}")
    if dry_run:
        reason = "MT5 tidak tersedia" if not ex.is_available() else "diminta"
        print(f"  mode    : 🧪 DRY-RUN ({reason}) — order TIDAK dieksekusi")
    else:
        print(f"  mode    : 🤖 LIVE — order DIKIRIM ke broker (uji DEMO dulu!)")
        print(f"  harga   : {'absolut dari master' if config.USE_MASTER_PRICES else 'hitung ulang dari jarak (tick client)'}")
    print("=" * 60)
    print(f"[{_now()}] menyambung ke master... (Ctrl+C untuk berhenti)")

    dedup = Dedup(config.DEDUP_TTL)
    delay = config.RECONNECT_MIN
    try:
        while True:
            try:
                listen_once(args.host, args.port, dry_run, dedup)
                # koneksi tertutup normal oleh master -> coba sambung lagi
                print(f"[{_now()}] koneksi master tertutup. Reconnect "
                      f"dalam {config.RECONNECT_MIN:.0f}s...")
                delay = config.RECONNECT_MIN
            except (ConnectionRefusedError, ConnectionResetError, OSError,
                    socket.timeout) as e:
                print(f"[{_now()}] [warn] koneksi gagal/putus: {e}. "
                      f"Reconnect dalam {delay:.0f}s...")
            time.sleep(delay)
            delay = min(delay * 1.6, config.RECONNECT_MAX)   # exponential backoff
    except KeyboardInterrupt:
        print("\nDihentikan.")


if __name__ == "__main__":
    main()
