# client-bot

Menerima sinyal dari **master-bot** lewat **socket (realtime)** lalu
mengeksekusi order BUY/SELL di **MetaTrader 5** (Windows).

```
master-bot (cari sinyal)                client-bot (eksekusi)
┌────────────────────────┐   socket    ┌────────────────────────┐
│ live_runner.py         │   TCP/JSON  │ signal_client.py       │
│   └─ signals_log.csv   │  ───────▶   │   └─ mt5_executor.py   │
│ signal_broadcaster.py  │  broadcast  │        └─ MetaTrader5  │
└────────────────────────┘             └────────────────────────┘
     SERVER :9009                            CLIENT (subscriber)
```

- **master-bot tidak diubah.** `signal_broadcaster.py` (file baru di master-bot)
  hanya **membaca** `signals_log.csv` dan mem-broadcast sinyal baru via socket.
- **client-bot** menyambung ke broadcaster, menerima JSON, dan membuka posisi MT5.
- Komunikasi **satu arah** (publish/subscribe), **NDJSON** (1 baris JSON / pesan),
  dengan **heartbeat** + **reconnect otomatis** agar tahan putus.

## Setup

```bash
cd client-bot
python -m venv .venv && source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
cp .env.example .env        # lalu isi MASTER_HOST, MT5_SYMBOL, TRADE_LOT, dst.
```

## Menjalankan

**Di mesin master** (mac/Windows tempat master jalan), berdampingan dengan runner:

```bash
cd master-bot
python3 live_runner.py            # master seperti biasa (TIDAK diubah)
python3 signal_broadcaster.py     # broadcaster: sebar sinyal via socket :9009
```

**Di mesin client** (Windows + MetaTrader 5 login broker):

```bash
cd client-bot
python signal_client.py           # konek ke MASTER_HOST:MASTER_PORT, eksekusi MT5
```

Bila master & client beda mesin: set `MASTER_HOST` di `.env` client ke IP master,
dan pastikan port (`9009`) terbuka di firewall master.

## Uji tanpa MT5 / tanpa master (di macOS pun bisa)

```bash
# Terminal 1 (master): kirim sinyal palsu tiap 10 detik
python3 master-bot/signal_broadcaster.py --demo

# Terminal 2 (client): mode simulasi, hanya cetak rencana order
python  client-bot/signal_client.py --dry-run --host 127.0.0.1
```

## Catatan harga TP/SL

- `USE_MASTER_PRICES=0` (default): client **menghitung ulang** TP/SL dari *jarak*
  (`tp_dist`/`sl_dist`) memakai harga tick broker **client sendiri** — lebih aman
  bila feed master & client berbeda.
- `USE_MASTER_PRICES=1`: pakai harga absolut TP/SL dari master apa adanya.

## Keamanan

⚠️ Order memakai **dana sungguhan** jika akun live. **Selalu uji di akun DEMO dulu.**
Di macOS/Linux (tanpa paket MetaTrader5) client otomatis jalan **DRY-RUN**
(hanya mencetak rencana order), berguna untuk menguji jalur socket.
