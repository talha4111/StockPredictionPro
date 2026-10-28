import argparse
import ast
import os
import sys
import time
from pathlib import Path

import paramiko


def _read_legacy_creds():
    for name in ("quick_log.py", "server_check.py"):
        path = Path(name)
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        vals = {}
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in {"HOST", "USER", "PASS"}
            ):
                vals[node.targets[0].id] = ast.literal_eval(node.value)
        if {"HOST", "USER", "PASS"} <= set(vals):
            return vals
    raise RuntimeError("Sunucu baglanti bilgisi bulunamadi.")


def connect():
    try:
        from remote_config import connect_ssh

        return connect_ssh(timeout=15)
    except Exception:
        creds = _read_legacy_creds()
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            creds["HOST"],
            username=creds["USER"],
            password=creds["PASS"],
            timeout=15,
        )
        return ssh


def run(ssh, cmd, timeout=20):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return out if out else err


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def section(title, body):
    print()
    print("-" * 78)
    print(title)
    print("-" * 78)
    print(body.strip() if body and body.strip() else "-")


def snapshot(ssh):
    service = run(
        ssh,
        "systemctl is-active quantbot.service; "
        "systemctl show quantbot.service -p MainPID -p NRestarts -p ActiveEnterTimestamp --no-pager",
    )

    runtime_cmd = r"""cd /root/QuantBot && ./venv/bin/python - <<'PY'
import json, os, time
p = 'runtime_status.json'
if not os.path.exists(p):
    print('runtime_status.json yok')
    raise SystemExit
d = json.load(open(p, encoding='utf-8'))
print('status_file=' + time.strftime('%F %T %Z', time.localtime(os.path.getmtime(p))))
for key in ['guncelleme_zamani', 'faz', 'bot_durumu', 'demo_kasa', 'demo_equity', 'demo_pnl', 'demo_realized_pnl', 'demo_unrealized_pnl', 'live_kasa', 'portfoy_isi_yuzde']:
    print(f'{key}={d.get(key)}')
dm = d.get('demo_muhasebe') or {}
if dm:
    print(
        'demo_muhasebe='
        f"net={float(dm.get('net_pnl_mtm', 0.0)):+.2f} "
        f"realized={float(dm.get('realized_net', 0.0)):+.2f} "
        f"open_delta={float(dm.get('open_pnl_delta', 0.0)):+.2f} "
        f"records={dm.get('income_kayit_sayisi', 0)}"
    )
hedge = d.get('hedge_sniper') or {}
if hedge:
    print('hedge_sniper=' + str(hedge))
sd = d.get('son_dongu') or {}
if sd:
    print('son_dongu=' + str(sd)[:300])
sh = d.get('son_hata') or {}
print('son_hata=' + (str(sh)[:300] if sh else 'yok'))
PY"""
    runtime = run(ssh, runtime_cmd, timeout=30)

    positions_cmd = r"""cd /root/QuantBot && ./venv/bin/python - <<'PY'
import sys
sys.path.insert(0, '/root/QuantBot')
from config import TESTNET_API_KEY, TESTNET_SECRET
import ccxt
b = ccxt.binanceusdm({
    'apiKey': TESTNET_API_KEY,
    'secret': TESTNET_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000},
})
b.enable_demo_trading(True)
count = 0
total = 0.0
for p in b.fetch_positions():
    info = p.get('info') or {}
    amount = float(info.get('positionAmt') or p.get('contracts') or 0)
    if not amount:
        continue
    pnl = float(p.get('unrealizedPnl') or info.get('unRealizedProfit') or 0)
    count += 1
    total += pnl
    print(f"{p.get('symbol'):<16} amount={amount:<10g} uPnL={pnl:+.4f}")
print(f"acik_pozisyon={count} toplam_uPnL={total:+.4f}")
PY"""
    positions = run(ssh, positions_cmd, timeout=45)

    session_cmd = r"""cd /root/QuantBot && ./venv/bin/python - <<'PY'
import json, os, sqlite3, subprocess
from datetime import datetime, timezone, timedelta
raw = subprocess.check_output(['systemctl', 'show', 'quantbot.service', '-p', 'ActiveEnterTimestamp', '--value'], text=True).strip()
start = datetime.strptime(raw, '%a %Y-%m-%d %H:%M:%S %Z').replace(tzinfo=timezone.utc)
start_naive = start.replace(tzinfo=None)
def parse_z(s):
    if not s:
        return None
    s = str(s).strip()
    for candidate in (s[:19], s):
        try:
            return datetime.strptime(candidate, '%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
    return None
def fnum(x):
    try:
        return float(x)
    except Exception:
        return 0.0
opened = 0
for path in ('demo_trade_journal.old.jsonl', 'demo_trade_journal.jsonl'):
    if not os.path.exists(path):
        continue
    with open(path, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            z = parse_z(e.get('zaman'))
            if z and z >= start_naive and e.get('tip') == 'acilis':
                opened += 1
closed = 0
realized = 0.0
official = None
try:
    status = json.load(open('runtime_status.json', encoding='utf-8'))
    dm = status.get('demo_muhasebe') or {}
    if dm and 'net_pnl_mtm' in dm:
        official = {
            'net': fnum(dm.get('net_pnl_mtm')),
            'realized': fnum(dm.get('realized_net')),
            'open_delta': fnum(dm.get('open_pnl_delta')),
            'records': dm.get('income_kayit_sayisi', 0),
        }
except Exception:
    pass
db = 'trading_bot.db'
if os.path.exists(db):
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute('SELECT Tarih_Saat, Net_PNL_USDT FROM closed_trades')
    for tarih, pnl in cur.fetchall():
        z = parse_z(tarih)
        if z and z >= start_naive:
            closed += 1
            realized += fnum(pnl)
    con.close()
tr = start + timedelta(hours=3)
print(f"baslangic_TR={tr:%Y-%m-%d %H:%M:%S}")
print(f"acilan={opened} kapanan={closed} db_kapanis_PnL={realized:+.2f} USDT")
if official:
    print(f"resmi_net_PnL={official['net']:+.2f} USDT")
    print(f"resmi_realized={official['realized']:+.2f} USDT")
    print(f"acik_pnl_farki={official['open_delta']:+.2f} USDT")
    print(f"income_kaydi={official['records']}")
PY"""
    session_stats = run(ssh, session_cmd, timeout=45)

    health_log = run(
        ssh,
        "tail -220 /root/QuantBot/bot.log 2>/dev/null | "
        "grep -E 'AÇIK POZİSYONLAR|Aktif İşlem Yok|DEMO\\]|PERFORMANS|ÇIKIŞ MOTORU|Kısmi kapanış|Traceback|KRİTİK HATA|ERROR|HATA' | tail -25 || true",
    )

    tail = run(ssh, "tail -18 /root/QuantBot/bot.log 2>/dev/null")
    return service, runtime, session_stats, positions, health_log, tail


def main():
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="QuantBot sunucu canli izleme paneli")
    parser.add_argument("--interval", type=int, default=5, help="Yenileme araligi saniye")
    args = parser.parse_args()

    ssh = connect()
    try:
        while True:
            service, runtime, session_stats, positions, health_log, tail = snapshot(ssh)
            clear()
            print("QUANTBOT CANLI IZLEME")
            print(f"Yenileme: {args.interval}s | Cikis: Ctrl+C | Yerel saat: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            section("SERVIS", service)
            section("BOT DURUMU", runtime)
            section("SON BASLATMADAN BERI", session_stats)
            section("ACIK POZISYONLAR", positions)
            section("ONEMLI LOG SATIRLARI", health_log)
            section("SON LOG", tail)
            time.sleep(max(2, args.interval))
    except KeyboardInterrupt:
        print("\nIzleme kapatildi. Bot sunucuda calismaya devam ediyor.")
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
