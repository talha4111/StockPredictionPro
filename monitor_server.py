import ast
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


def run(ssh, cmd, timeout=30):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return out, err


def print_block(title, body):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)
    print(body.strip() if body.strip() else "-")


def main():
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ssh = connect()
    try:
        service, err = run(
            ssh,
            "systemctl is-active quantbot.service; "
            "systemctl is-enabled quantbot.service; "
            "systemctl show quantbot.service -p MainPID -p NRestarts -p Restart -p ActiveEnterTimestamp --no-pager",
        )
        print_block("SERVIS", service or err)

        process, _ = run(
            ssh,
            "ps -eo pid,ppid,stat,etime,pcpu,pmem,rss,args | awk '/[p]ython .*main.py/{print}'",
        )
        print_block("BOT SURECI", process or "Bot process gorunmuyor.")

        before, _ = run(ssh, "stat -c %s /root/QuantBot/bot.log 2>/dev/null || echo 0")
        time.sleep(5)
        after, _ = run(ssh, "stat -c '%s %y' /root/QuantBot/bot.log 2>/dev/null || echo '0 log_yok'")
        before_size = int(str(before).splitlines()[-1] or 0)
        after_parts = after.split(maxsplit=1)
        after_size = int(after_parts[0] or 0)
        growth = after_size - before_size
        log_status = f"Log 5 saniyede {growth} byte buyudu.\nSon log zamani: {after_parts[1] if len(after_parts) > 1 else '?'}"
        print_block("LOG CANLILIGI", log_status)

        status_cmd = r"""cd /root/QuantBot && ./venv/bin/python - <<'PY'
import json, os, time
p = 'runtime_status.json'
if not os.path.exists(p):
    print('runtime_status.json yok')
    raise SystemExit
d = json.load(open(p, encoding='utf-8'))
print('dosya_zamani=' + time.strftime('%F %T %Z', time.localtime(os.path.getmtime(p))))
for key in ['guncelleme_zamani', 'faz', 'bot_durumu', 'live_mod', 'live_tetik', 'demo_kasa', 'demo_equity', 'demo_pnl', 'demo_realized_pnl', 'demo_unrealized_pnl', 'live_kasa', 'portfoy_isi_yuzde']:
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
    print('son_dongu=' + str(sd)[:500])
sh = d.get('son_hata') or {}
print('son_hata=' + (str(sh)[:500] if sh else 'yok'))
PY"""
        status, err = run(ssh, status_cmd)
        print_block("BOT DURUM DOSYASI", status or err)

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
print(f"acilan={opened}")
print(f"kapanan={closed}")
print(f"db_kapanis_PnL={realized:+.2f} USDT")
if official:
    print(f"resmi_net_PnL={official['net']:+.2f} USDT")
    print(f"resmi_realized={official['realized']:+.2f} USDT")
    print(f"acik_pnl_farki={official['open_delta']:+.2f} USDT")
    print(f"income_kaydi={official['records']}")
PY"""
        session_stats, err = run(ssh, session_cmd, timeout=45)
        print_block("SON BASLATMADAN BERI", session_stats or err)

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
    print(f"{p.get('symbol')} amount={amount} uPnL={pnl:+.4f}")
print(f"acik_pozisyon={count} toplam_uPnL={total:+.4f}")
PY"""
        positions, err = run(ssh, positions_cmd, timeout=60)
        print_block("ACIK POZISYONLAR", positions or err)

        recent, _ = run(
            ssh,
            "tail -250 /root/QuantBot/bot.log 2>/dev/null | "
            "grep -Ei 'Traceback|Exception|ERROR|HATA|KRITIK|CRITICAL|failed|basarisiz|başarısız' | tail -20 || true",
        )
        print_block("SON HATA SATIRLARI", recent or "Son 250 log satirinda kritik hata gorunmedi.")

        tail, _ = run(ssh, "tail -35 /root/QuantBot/bot.log 2>/dev/null")
        print_block("SON LOG", tail)
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
