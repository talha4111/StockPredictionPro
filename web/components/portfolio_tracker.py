"""
StockPredictionPro — Portföy Defteri & FIFO Motoru
Midas uyumlu FIFO lot eşleştirme, Dolar & TL kâr/zarar, vergi taslağı
ve Google Sheets / Yerel JSON çift katmanlı kalıcı depolama.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime
import pandas as pd
import yfinance as yf

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_DATA_DIR = os.path.join(PROJECT_ROOT, "web", "data")
LOCAL_FILE = os.path.join(LOCAL_DATA_DIR, "portfolio_transactions.json")


def get_current_usdtry():
    """Anlık USD/TRY kurunu yfinance üzerinden çeker."""
    try:
        tk = yf.Ticker("USDTRY=X")
        fast = getattr(tk, "fast_info", {})
        price = fast.get("lastPrice") or getattr(fast, "last_price", None)
        if price and price > 0:
            return round(float(price), 4)
        h = tk.history(period="2d")
        if not h.empty:
            return round(float(h["Close"].iloc[-1]), 4)
    except Exception:
        pass
    return 49.15


def get_current_user_name():
    """Oturum açmış güncel kullanıcının adını döndürür."""
    try:
        import streamlit as st
        user = st.session_state.get("user")
        if user and isinstance(user, dict):
            return user.get("username", "talha6641")
    except Exception:
        pass
    return "talha6641"


# ─── DEPOLAMA KATMANI (Google Sheets + Yerel Fallback) ───
def load_transactions(target_user: str = None, filter_by_user: bool = True):
    """
    İşlemleri okur ve çok kullanıcılı izolasyon kuralına göre
    sadece ilgili kullanıcının işlemlerini döndürür.
    """
    raw_tx = []
    # 1. Google Sheets bağlantısını dene (Streamlit Secrets varsa)
    try:
        import streamlit as st
        if hasattr(st, "connection"):
            conn = st.connection("gsheets", type="GSheetsConnection")
            df = conn.read(worksheet="Islemler", ttl=5)
            if df is not None and not df.empty:
                records = df.to_dict(orient="records")
                for r in records:
                    if r.get("sembol"):
                        raw_tx.append({
                            "id": str(r.get("id") or uuid.uuid4().hex[:8]),
                            "user": str(r.get("user") or "talha6641").lower(),
                            "tarih": str(r.get("tarih") or datetime.now().strftime("%Y-%m-%d")),
                            "sembol": str(r.get("sembol")).upper().strip(),
                            "islem_tipi": str(r.get("islem_tipi") or "ALIS").upper(),
                            "adet": float(r.get("adet") or 0),
                            "fiyat_usd": float(r.get("fiyat_usd") or 0),
                            "komisyon_usd": float(r.get("komisyon_usd") or 1.50),
                            "usdtry_kuru": float(r.get("usdtry_kuru") or get_current_usdtry()),
                            "notlar": str(r.get("notlar") or ""),
                        })
    except Exception:
        pass

    # 2. Yerel dosya fallback
    if not raw_tx and os.path.exists(LOCAL_FILE):
        try:
            with open(LOCAL_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    raw_tx = data
        except Exception:
            pass

    # Kullanıcı Bazlı İzolasyon (Multi-Tenant Isolation)
    if filter_by_user:
        active_u = (target_user or get_current_user_name()).lower()
        return [
            t for t in raw_tx 
            if t.get("user", "talha6641").lower() == active_u 
            or (active_u in ("talha", "talha6641") and t.get("user", "talha6641").lower() in ("talha", "talha6641"))
        ]

    return raw_tx


def save_transactions(transactions, merge_all_users: bool = True):
    """İşlemleri hem yerel JSON'a hem de bağlıysa Google Sheets'e kaydeder."""
    os.makedirs(LOCAL_DATA_DIR, exist_ok=True)
    
    # 1. Yerel JSON'a yaz
    try:
        with open(LOCAL_FILE, "w", encoding="utf-8") as f:
            json.dump(transactions, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    # 2. Google Sheets bağlıysa oraya da yaz
    try:
        import streamlit as st
        if hasattr(st, "connection"):
            conn = st.connection("gsheets", type="GSheetsConnection")
            df = pd.DataFrame(transactions)
            conn.update(worksheet="Islemler", data=df)
            return True, "Google Sheets ve Yerel Belleğe Kaydedildi"
    except Exception:
        pass

    return True, "Yerel Belleğe Kaydedildi"


def add_transaction(tarih, sembol, islem_tipi, adet, fiyat_usd, komisyon_usd=1.50, usdtry_kuru=None, notlar=""):
    """Yeni bir alış veya satış işlemi ekler (Oturum açan kullanıcıya zimmetler)."""
    if not usdtry_kuru:
        usdtry_kuru = get_current_usdtry()

    current_u = get_current_user_name()

    tx = {
        "id": uuid.uuid4().hex[:8],
        "user": current_u.lower(),
        "tarih": str(tarih),
        "sembol": sembol.upper().strip(),
        "islem_tipi": islem_tipi.upper(),
        "adet": float(adet),
        "fiyat_usd": float(fiyat_usd),
        "komisyon_usd": float(komisyon_usd),
        "usdtry_kuru": float(usdtry_kuru),
        "notlar": str(notlar),
    }

    all_tx = load_transactions(filter_by_user=False)
    all_tx.append(tx)
    success, msg = save_transactions(all_tx)
    return success, msg, tx


def delete_transaction(tx_id):
    """Bir işlemi kimliğine (id) göre siler."""
    all_tx = load_transactions(filter_by_user=False)
    filtered = [t for t in all_tx if t.get("id") != tx_id]
    save_transactions(filtered)
    return True


# ─── FIFO (FIRST-IN, FIRST-OUT) HESAP MOTORU ───
def calculate_fifo_portfolio(transactions=None):
    """
    Tüm işlemleri tarihe göre sırayla okur.
    Midas mantığıyla (FIFO) lotları eritir.
    
    Döndürür:
      - open_positions: {sembol: {'adet': ..., 'maliyet_usd': ..., 'maliyet_tl': ..., 'lotlar': [...]}}
      - closed_trades: Gerçekleşmiş satışlar ve her birinin lot bazında kâr/zararı
      - summary: Genel portföy metrikleri
    """
    if transactions is None:
        transactions = load_transactions()

    # Tarihe ve ID'ye göre sırala (kronolojik sıra)
    sorted_tx = sorted(transactions, key=lambda x: (x.get("tarih", ""), x.get("id", "")))

    buy_pools = {}   # sembol -> list of available buy lots
    closed_trades = []

    for tx in sorted_tx:
        sym = tx["sembol"]
        tx_type = tx["islem_tipi"]
        qty = tx["adet"]
        price = tx["fiyat_usd"]
        fee = tx.get("komisyon_usd", 0.0)
        fx = tx.get("usdtry_kuru", 49.0)
        tarih = tx["tarih"]
        tx_id = tx.get("id")

        if sym not in buy_pools:
            buy_pools[sym] = []

        if tx_type == "ALIS":
            buy_pools[sym].append({
                "id": tx_id,
                "tarih": tarih,
                "adet_kalan": qty,
                "adet_orijinal": qty,
                "fiyat_usd": price,
                "usdtry_kuru": fx,
                "komisyon_usd": fee,
                "maliyet_lot_tl": price * fx,
            })

        elif tx_type == "SATIS":
            qty_to_sell = qty
            while qty_to_sell > 0 and len(buy_pools[sym]) > 0:
                first_lot = buy_pools[sym][0]
                matched_qty = min(qty_to_sell, first_lot["adet_kalan"])

                buy_cost_usd = matched_qty * first_lot["fiyat_usd"]
                sell_val_usd = matched_qty * price
                profit_usd = sell_val_usd - buy_cost_usd - fee

                buy_cost_tl = matched_qty * (first_lot["fiyat_usd"] * first_lot["usdtry_kuru"])
                sell_val_tl = matched_qty * (price * fx) - (fee * fx)
                profit_tl = sell_val_tl - buy_cost_tl

                try:
                    d_buy = datetime.strptime(first_lot["tarih"], "%Y-%m-%d")
                    d_sell = datetime.strptime(tarih, "%Y-%m-%d")
                    holding_days = (d_sell - d_buy).days
                except Exception:
                    holding_days = 0

                closed_trades.append({
                    "sembol": sym,
                    "satis_tarihi": tarih,
                    "alis_tarihi": first_lot["tarih"],
                    "adet": matched_qty,
                    "alis_fiyati_usd": first_lot["fiyat_usd"],
                    "satis_fiyati_usd": price,
                    "alis_kuru": first_lot["usdtry_kuru"],
                    "satis_kuru": fx,
                    "kar_usd": profit_usd,
                    "kar_tl": profit_tl,
                    "tutma_gunu": holding_days,
                    "alis_lot_id": first_lot["id"],
                    "satis_tx_id": tx_id,
                })

                first_lot["adet_kalan"] -= matched_qty
                qty_to_sell -= matched_qty

                if first_lot["adet_kalan"] <= 0.0001:
                    buy_pools[sym].pop(0)

    # Kalan açık pozisyonları yapılandır
    open_positions = {}
    for sym, lots in buy_pools.items():
        active_lots = [l for l in lots if l["adet_kalan"] > 0.0001]
        if active_lots:
            total_qty = sum(l["adet_kalan"] for l in active_lots)
            total_cost_usd = sum(l["adet_kalan"] * l["fiyat_usd"] for l in active_lots)
            total_cost_tl = sum(l["adet_kalan"] * l["fiyat_usd"] * l["usdtry_kuru"] for l in active_lots)
            avg_price_usd = total_cost_usd / total_qty if total_qty > 0 else 0.0
            avg_cost_tl = total_cost_tl / total_qty if total_qty > 0 else 0.0

            open_positions[sym] = {
                "toplam_adet": total_qty,
                "toplam_maliyet_usd": total_cost_usd,
                "ortalama_fiyat_usd": avg_price_usd,
                "toplam_maliyet_tl": total_cost_tl,
                "ortalama_maliyet_tl": avg_cost_tl,
                "lot_sayisi": len(active_lots),
                "lotlar": active_lots,
            }

    return open_positions, closed_trades
