"""Eksekusi order via MetaTrader 5 untuk client-bot (KHUSUS Windows).

Menerima sinyal (BUY/SELL + TP/SL) dari master lewat socket, lalu membuka posisi
market di terminal MT5 yang sudah login ke broker. Modul ini BERDIRI SENDIRI
(tidak bergantung pada master-bot) dan meniru logika eksekusi master:
filling mode otomatis, magic number, deviation, dan batas posisi terbuka.

Prasyarat (Windows):
  1. pip install MetaTrader5
  2. Terminal MetaTrader 5 ter-install & login ke akun broker (DEMO dulu!).
  3. Isi .env (lihat .env.example): MT5_SYMBOL, TRADE_LOT, MAX_OPEN_POSITIONS, dst.

Di macOS/Linux modul MetaTrader5 tidak ada -> is_available()=False, dan
signal_client otomatis jalan dalam mode DRY-RUN (hanya cetak rencana order).
"""
import platform
import config

try:
    import MetaTrader5 as mt5
except ImportError:   # bukan Windows / paket belum diinstall
    mt5 = None

_INITIALIZED = False


def is_available():
    """True hanya bila berjalan di Windows dengan paket MetaTrader5 terpasang."""
    return platform.system() == "Windows" and mt5 is not None


def _ensure_init():
    """Inisialisasi koneksi ke terminal MT5 (sekali saja)."""
    global _INITIALIZED
    if mt5 is None:
        raise RuntimeError(
            "Paket MetaTrader5 tidak tersedia. Jalankan `pip install MetaTrader5` "
            "di Windows dengan terminal MetaTrader 5 ter-install."
        )
    if _INITIALIZED:
        return
    kwargs = {}
    if config.MT5_PATH:
        kwargs["path"] = config.MT5_PATH
    if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
        kwargs["login"] = int(config.MT5_LOGIN)
        kwargs["password"] = config.MT5_PASSWORD
        kwargs["server"] = config.MT5_SERVER
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"mt5.initialize() gagal: {mt5.last_error()}")
    _INITIALIZED = True


def _symbol(code=None):
    """Pastikan simbol ada & tampil di Market Watch, kembalikan namanya."""
    sym = code or config.MT5_SYMBOL
    info = mt5.symbol_info(sym)
    if info is None:
        raise RuntimeError(
            f"Simbol '{sym}' tidak ditemukan di MT5. Cek nama simbol di broker "
            f"(mis. XAUUSD, XAUUSDm, GOLD) lalu set MT5_SYMBOL di .env."
        )
    if not info.visible:
        mt5.symbol_select(sym, True)
    return sym


def _pick_filling(sym):
    """Tentukan mode filling yang didukung simbol (FOK/IOC/RETURN)."""
    mapping = {
        "ioc": mt5.ORDER_FILLING_IOC,
        "fok": mt5.ORDER_FILLING_FOK,
        "return": mt5.ORDER_FILLING_RETURN,
    }
    if config.TRADE_FILLING in mapping:
        return mapping[config.TRADE_FILLING]
    info = mt5.symbol_info(sym)
    fm = getattr(info, "filling_mode", 0) if info else 0
    if fm & 2:
        return mt5.ORDER_FILLING_IOC
    if fm & 1:
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


def count_open_positions(sym=None):
    """Jumlah posisi bot (magic = config.TRADE_MAGIC) yang sedang terbuka."""
    if not is_available():
        return 0
    _ensure_init()
    sym = sym or config.MT5_SYMBOL
    positions = mt5.positions_get(symbol=sym)
    if positions is None:
        return 0
    return sum(1 for p in positions if p.magic == config.TRADE_MAGIC)


def resolve_prices(signal):
    """Tentukan harga entry/TP/SL absolut untuk dieksekusi.

    Jika USE_MASTER_PRICES=1 -> pakai tp/sl absolut dari master apa adanya.
    Jika 0 (default) -> hitung ulang dari JARAK (tp_dist/sl_dist) memakai
    tick broker client (lebih aman saat feed master & client berbeda).
    Mengembalikan (entry_price, tp_price, sl_price).
    """
    side = signal["side"]
    if config.USE_MASTER_PRICES or not is_available():
        # Mode dry-run di non-Windows juga lewat sini (tanpa akses tick).
        return signal.get("price"), signal.get("tp"), signal.get("sl")

    _ensure_init()
    sym = _symbol()
    tick = mt5.symbol_info_tick(sym)
    if tick is None:
        raise RuntimeError(f"tidak dapat tick untuk {sym}.")
    tp_dist = float(signal["tp_dist"])
    sl_dist = float(signal["sl_dist"])
    if side == "BUY":
        entry = tick.ask
        return entry, entry + tp_dist, entry - sl_dist
    else:  # SELL
        entry = tick.bid
        return entry, entry - tp_dist, entry + sl_dist


def open_position(signal, lot=None, comment="client"):
    """Buka posisi market sesuai sinyal master.

    signal: dict berisi side, tp/sl (absolut) + tp_dist/sl_dist (jarak).
    Mengembalikan (result, error_str). Sukses -> error_str=None.
    """
    if not is_available():
        return None, "MT5 tidak tersedia (hanya Windows + paket MetaTrader5)."
    try:
        _ensure_init()
        sym = _symbol()
    except Exception as e:
        return None, f"init/simbol MT5 gagal: {e}"

    side = signal["side"]
    lot = float(lot or config.TRADE_LOT)
    tick = mt5.symbol_info_tick(sym)
    info = mt5.symbol_info(sym)
    if tick is None or info is None:
        return None, f"tidak dapat tick/info untuk {sym}."

    if side == "BUY":
        order_type, price = mt5.ORDER_TYPE_BUY, tick.ask
    elif side == "SELL":
        order_type, price = mt5.ORDER_TYPE_SELL, tick.bid
    else:
        return None, f"side tidak dikenal: {side}"

    _, tp_price, sl_price = resolve_prices(signal)
    digits = info.digits
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": sym,
        "volume": lot,
        "type": order_type,
        "price": float(price),
        "sl": round(float(sl_price), digits),
        "tp": round(float(tp_price), digits),
        "deviation": config.TRADE_DEVIATION,
        "magic": config.TRADE_MAGIC,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _pick_filling(sym),
    }
    result = mt5.order_send(request)
    if result is None:
        return None, f"order_send None: {mt5.last_error()}"
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return result, f"order ditolak retcode={result.retcode} ({result.comment})"
    return result, None


if __name__ == "__main__":
    print("MT5 tersedia:", is_available())
    if is_available():
        print("posisi bot terbuka:", count_open_positions())
