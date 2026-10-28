import os
import json

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- .env Dosyasını Otomatik Yükle ---
_env_path = os.path.join(_BASE_DIR, '.env')
try:
    from dotenv import load_dotenv
    load_dotenv(_env_path, override=False)
except ImportError:
    if os.path.exists(_env_path):
        with open(_env_path, 'r', encoding='utf-8') as _ef:
            for _line in _ef:
                _line = _line.strip()
                if '=' in _line and not _line.startswith('#'):
                    _k, _v = _line.split('=', 1)
                    if _k.strip() not in os.environ:
                        os.environ[_k.strip()] = _v.strip().strip('"').strip("'")

# --- ayar.json Yükleme ---
_ayar_path = os.path.join(_BASE_DIR, 'ayar.json')
try:
    with open(_ayar_path, 'r', encoding='utf-8') as f:
        AYAR = json.load(f)
    PORTFOY = AYAR.get("portfoy", [])
    REF = AYAR.get("referans_varlik", "BTC/USDT")
    RISK_AYAR = AYAR.get("risk_yonetimi", {})
    TELEGRAM_AYAR = AYAR.get("telegram", {})
    
    # CCXT Testnet Ayarları
    TESTNET_API_KEY = AYAR.get("testnet_api_key", "").strip()
    TESTNET_SECRET = AYAR.get("testnet_secret", "").strip()
    ISLEM_MIKTARI_USDT = AYAR.get("islem_miktari_usdt", 50)
    SL_YUZDE = AYAR.get("sl_yuzde", 0.01)
    TP_YUZDE = AYAR.get("tp_yuzde", 0.02)
except Exception as e:
    print(f"⚠️ [KRİTİK UYARI] ayar.json okunamadı veya bozuk! Bot varsayılan ayarlar ile zorla başlatılıyor... Hata: {e}")
    AYAR = {}
    PORTFOY = []
    REF = "BTC/USDT"
    RISK_AYAR = {"tp_atr_carpani": 2.0}
    TELEGRAM_AYAR = {"aktif_mi": False}
    TESTNET_API_KEY = ""
    TESTNET_SECRET = ""
    ISLEM_MIKTARI_USDT = 11.5
    SL_YUZDE = 0.01
    TP_YUZDE = 0.02

# .env veya OS çevresel değişkenlerinden üstüne yaz
TESTNET_API_KEY = os.environ.get('TESTNET_API_KEY', TESTNET_API_KEY).strip()
TESTNET_SECRET = os.environ.get('TESTNET_SECRET', TESTNET_SECRET).strip()

if not TELEGRAM_AYAR.get('aktif_mi'):
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        TELEGRAM_AYAR = {
            "aktif_mi": True,
            "bot_token": TELEGRAM_BOT_TOKEN,
            "chat_id": TELEGRAM_CHAT_ID
        }

SEKTORLER = {
    'BTC/USDT': 'Piyasa Lideri', 'BTCUSDT': 'Piyasa Lideri',
    'ETH/USDT': 'Katman-1', 'ETHUSDT': 'Katman-1',
    'SOL/USDT': 'Katman-1', 'SOLUSDT': 'Katman-1',
    'AVAX/USDT': 'Katman-1', 'AVAXUSDT': 'Katman-1',
    'ADA/USDT': 'Katman-1', 'ADAUSDT': 'Katman-1',
    'NEAR/USDT': 'Katman-1', 'NEARUSDT': 'Katman-1',
    'SUI/USDT': 'Katman-1', 'SUIUSDT': 'Katman-1',
    'APT/USDT': 'Katman-1', 'APTUSDT': 'Katman-1',
    'TIA/USDT': 'Katman-1', 'TIAUSDT': 'Katman-1',
    'SEI/USDT': 'Katman-1', 'SEIUSDT': 'Katman-1',
    'TON/USDT': 'Katman-1', 'TONUSDT': 'Katman-1',
    'BNB/USDT': 'Borsa', 'BNBUSDT': 'Borsa',
    'LINK/USDT': 'Oracle', 'LINKUSDT': 'Oracle',
    'DOT/USDT': 'Interop', 'DOTUSDT': 'Interop',
    'ATOM/USDT': 'Interop', 'ATOMUSDT': 'Interop',
    'LTC/USDT': 'Ödeme', 'LTCUSDT': 'Ödeme',
    'XRP/USDT': 'Ödeme', 'XRPUSDT': 'Ödeme',
    'DOGE/USDT': 'Meme', 'DOGEUSDT': 'Meme',
    'SHIB/USDT': 'Meme', 'SHIBUSDT': 'Meme',
    'PEPE/USDT': 'Meme', 'PEPEUSDT': 'Meme',
    'WIF/USDT': 'Meme', 'WIFUSDT': 'Meme',
    'FLOKI/USDT': 'Meme', 'FLOKIUSDT': 'Meme',
    'BONK/USDT': 'Meme', 'BONKUSDT': 'Meme',
    'FET/USDT': 'AI', 'FETUSDT': 'AI',
    'RENDER/USDT': 'AI', 'RENDERUSDT': 'AI',
    'TAO/USDT': 'AI', 'TAOUSDT': 'AI',
    'WLD/USDT': 'AI', 'WLDUSDT': 'AI',
    'UNI/USDT': 'DeFi', 'UNIUSDT': 'DeFi',
    'AAVE/USDT': 'DeFi', 'AAVEUSDT': 'DeFi',
    'MKR/USDT': 'DeFi', 'MKRUSDT': 'DeFi',
    'PENDLE/USDT': 'DeFi', 'PENDLEUSDT': 'DeFi',
    'IMX/USDT': 'Gaming', 'IMXUSDT': 'Gaming',
    'GALA/USDT': 'Gaming', 'GALAUSDT': 'Gaming',
    'AXS/USDT': 'Gaming', 'AXSUSDT': 'Gaming',
    'OP/USDT': 'Katman-2', 'OPUSDT': 'Katman-2',
    'ARB/USDT': 'Katman-2', 'ARBUSDT': 'Katman-2',
    'MATIC/USDT': 'Katman-2', 'MATICUSDT': 'Katman-2',
    'POL/USDT': 'Katman-2', 'POLUSDT': 'Katman-2',
    'PENGU/USDT': 'Meme', 'PENGUUSDT': 'Meme',
    'PNUT/USDT': 'Meme', 'PNUTUSDT': 'Meme',
    'TRUMP/USDT': 'Meme', 'TRUMPUSDT': 'Meme',
    'HMSTR/USDT': 'Gaming', 'HMSTRUSDT': 'Gaming',
    'EIGEN/USDT': 'Katman-1', 'EIGENUSDT': 'Katman-1',
    'GRT/USDT': 'Data', 'GRTUSDT': 'Data',
    'KITE/USDT': 'Diğer', 'KITEUSDT': 'Diğer',
    'VIRTUAL/USDT': 'AI', 'VIRTUALUSDT': 'AI',
    'MOVE/USDT': 'Katman-1', 'MOVEUSDT': 'Katman-1',
    'INJ/USDT': 'DeFi', 'INJUSDT': 'DeFi',
    'PUMP/USDT': 'Meme', 'PUMPUSDT': 'Meme',
}

# --- GLOBAL DEĞİŞKENLER & AYARLAR ---
ALIM_SATIM_TETIGI_ACIK = False
LIVE_MOD_AKTIF = False
MAX_LIVE_MARGIN_YUZDESI = 0.20
MAX_DEMO_MARGIN_YUZDESI = 0.25
DEMO_MIN_MARGIN_YUZDESI = 0.20
DEMO_DEFANSIF_MARGIN_CARPANI = 1.00
MAX_POZISYON_ZARAR_YUZDESI = 0.04
HEDEF_POZISYON_RISK_YUZDESI = 0.035
MIN_EMIR_NOTIONAL_USDT = 5.0
MIN_ANALIZ_MUM_SAYISI = 200
MAX_VERI_YASI_DAKIKA = float(AYAR.get("max_veri_yasi_dakika", 480.0))
MAX_ATR_FIYAT_YUZDESI = 15.0

DEMO_PROFIL_KESIF = "KESIF"
DEMO_PROFIL_LIVE_SHADOW = "LIVE_SHADOW"
DEMO_CALISMA_PROFILI = str(
    os.environ.get("DEMO_CALISMA_PROFILI")
    or os.environ.get("DEMO_PROFILE")
    or AYAR.get("demo_calisma_profili", DEMO_PROFIL_LIVE_SHADOW)
).strip().upper()

if DEMO_CALISMA_PROFILI not in {DEMO_PROFIL_KESIF, DEMO_PROFIL_LIVE_SHADOW}:
    print(f"[DEMO-PROFIL] Bilinmeyen profil '{DEMO_CALISMA_PROFILI}', LIVE_SHADOW kullaniliyor.")
    DEMO_CALISMA_PROFILI = DEMO_PROFIL_LIVE_SHADOW

DEMO_LIVE_SHADOW_AKTIF = DEMO_CALISMA_PROFILI == DEMO_PROFIL_LIVE_SHADOW

SHORT_ISLEM_AKTIF = str(
    os.environ.get("SHORT_ISLEM_AKTIF")
    or AYAR.get("short_islem_aktif", "false")
).strip().lower() in {"1", "true", "evet", "yes", "on"}

TEK_DONGU_TANI_MODU = str(
    os.environ.get("TEK_DONGU_TANI_MODU")
    or AYAR.get("tek_dongu_tani_modu", "false")
).strip().lower() in {"1", "true", "evet", "yes", "on"}

MODEL_KALITE_KAPISI_AKTIF = str(
    os.environ.get("MODEL_KALITE_KAPISI_AKTIF")
    or AYAR.get("model_kalite_kapisi_aktif", "true")
).strip().lower() in {"1", "true", "evet", "yes", "on"}

MODEL_KALITE_BILINMEYENI_ENGELLE = str(
    os.environ.get("MODEL_KALITE_BILINMEYENI_ENGELLE")
    or AYAR.get("model_kalite_bilinmeyeni_engelle", "true")
).strip().lower() in {"1", "true", "evet", "yes", "on"}

def _pozitif_float_ayar(env_ad, ayar_ad, varsayilan):
    try:
        ham = os.environ.get(env_ad)
        if ham is None or str(ham).strip() == "":
            ham = AYAR.get(ayar_ad, varsayilan)
        deger = float(ham)
        return deger if deger > 0 else varsayilan
    except Exception:
        return varsayilan

def _pozitif_int_ayar(env_ad, ayar_ad, varsayilan):
    try:
        ham = os.environ.get(env_ad)
        if ham is None or str(ham).strip() == "":
            ham = AYAR.get(ayar_ad, varsayilan)
        deger = int(float(ham))
        return deger if deger > 0 else varsayilan
    except Exception:
        return varsayilan

def _bool_ayar(env_ad, ayar_ad, varsayilan=False):
    try:
        ham = os.environ.get(env_ad)
        if ham is None or str(ham).strip() == "":
            ham = AYAR.get(ayar_ad, varsayilan)
        if isinstance(ham, bool):
            return ham
        return str(ham).strip().lower() in {"1", "true", "evet", "yes", "on", "aktif"}
    except Exception:
        return bool(varsayilan)

def _yuzde_ayar(env_ad, ayar_ad, varsayilan):
    deger = _pozitif_float_ayar(env_ad, ayar_ad, varsayilan)
    return deger / 100.0 if deger > 1.0 else deger

MIN_SCOUT_QUOTE_VOLUME_USDT = _pozitif_float_ayar("MIN_SCOUT_QUOTE_VOLUME_USDT", "min_scout_quote_volume_usdt", 50_000_000)
MAX_SCOUT_COIN_SAYISI = _pozitif_int_ayar("MAX_SCOUT_COIN_SAYISI", "max_scout_coin_sayisi", 100)
TANI_MAX_COIN_SAYISI = _pozitif_int_ayar("TANI_MAX_COIN_SAYISI", "tani_max_coin_sayisi", 20)
DEMO_EMIR_AKTIF = _bool_ayar("DEMO_EMIR_AKTIF", "demo_emir_aktif", False)
MODEL_YENIDEN_EGITIM_ZORLA = _bool_ayar("MODEL_YENIDEN_EGITIM_ZORLA", "model_yeniden_egitim_zorla", False)
BOOTCAMP_AKTIF = _bool_ayar("BOOTCAMP_AKTIF", "bootcamp_aktif", False)
MIN_MODEL_SCHEMA_VERSION = _pozitif_int_ayar("MIN_MODEL_SCHEMA_VERSION", "min_model_schema_version", 5)
MIN_MODEL_WALK_FORWARD_SKORU = _pozitif_float_ayar("MIN_MODEL_WALK_FORWARD_SKORU", "min_model_walk_forward_skoru", 0.52)
MODEL_KALITE_SARI_ESIK = _pozitif_float_ayar("MODEL_KALITE_SARI_ESIK", "model_kalite_sari_esik", 0.54)
MODEL_KALITE_SARI_MARGIN_CARPANI = _pozitif_float_ayar("MODEL_KALITE_SARI_MARGIN_CARPANI", "model_kalite_sari_margin_carpani", 0.70)
MODEL_RECENT_MIN_SIGNAL = _pozitif_int_ayar("MODEL_RECENT_MIN_SIGNAL", "model_recent_min_signal", 8)
MODEL_RECENT_MAX_BRIER = _pozitif_float_ayar("MODEL_RECENT_MAX_BRIER", "model_recent_max_brier", 0.26)
MODEL_RECENT_MIN_BRIER_SKILL = _pozitif_float_ayar("MODEL_RECENT_MIN_BRIER_SKILL", "model_recent_min_brier_skill", 0.001)
MODEL_RECENT_MIN_PROFIT_FACTOR = _pozitif_float_ayar("MODEL_RECENT_MIN_PROFIT_FACTOR", "model_recent_min_profit_factor", 1.10)
HEDGE_SNIPER_MODU_AKTIF = _bool_ayar("HEDGE_SNIPER_MODU_AKTIF", "hedge_sniper_modu_aktif", True)
HEDGE_MIN_RR = _pozitif_float_ayar("HEDGE_MIN_RR", "hedge_min_rr", 1.5)
HEDGE_MIN_GUVEN = _pozitif_float_ayar("HEDGE_MIN_GUVEN", "hedge_min_guven", 54.0)
HEDGE_MIN_ADX = _pozitif_float_ayar("HEDGE_MIN_ADX", "hedge_min_adx", 16.0)
HEDGE_MAX_CHOP = _pozitif_float_ayar("HEDGE_MAX_CHOP", "hedge_max_chop", 65.0)
HEDGE_MIN_VOLUME_ZSCORE = _pozitif_float_ayar("HEDGE_MIN_VOLUME_ZSCORE", "hedge_min_volume_zscore", 0.0)
HEDGE_ESCAPE_GUVEN = _pozitif_float_ayar("HEDGE_ESCAPE_GUVEN", "hedge_escape_guven", 65.0)
HEDGE_ESCAPE_RR = _pozitif_float_ayar("HEDGE_ESCAPE_RR", "hedge_escape_rr", 2.0)
HEDGE_MARGIN_CARPANI = max(0.20, min(1.0, _pozitif_float_ayar("HEDGE_MARGIN_CARPANI", "hedge_margin_carpani", 0.75)))
HEDGE_MAX_ESANLI_POZISYON = _pozitif_int_ayar("HEDGE_MAX_ESANLI_POZISYON", "hedge_max_esanli_pozisyon", 3)
HEDGE_MAX_DONGU_ISLEM = _pozitif_int_ayar("HEDGE_MAX_DONGU_ISLEM", "hedge_max_dongu_islem", 1)
HEDGE_DEFANSIF_PNL_PENCERE = _pozitif_int_ayar("HEDGE_DEFANSIF_PNL_PENCERE", "hedge_defansif_pnl_pencere", 5)
HEDGE_DEFANSIF_ZARAR_ESIK = _pozitif_float_ayar("HEDGE_DEFANSIF_ZARAR_ESIK", "hedge_defansif_zarar_esik", 3.0)
SYMBOL_GUARD_AKTIF = _bool_ayar("SYMBOL_GUARD_AKTIF", "symbol_guard_aktif", True)
SYMBOL_GUARD_PNL_ESIK = _pozitif_float_ayar("SYMBOL_GUARD_PNL_ESIK", "symbol_guard_pnl_esik", 4.0)
SYMBOL_GUARD_ARDISIK_ZARAR = _pozitif_int_ayar("SYMBOL_GUARD_ARDISIK_ZARAR", "symbol_guard_ardisik_zarar", 1)
SYMBOL_GUARD_KARANTINA_SAAT = _pozitif_float_ayar("SYMBOL_GUARD_KARANTINA_SAAT", "symbol_guard_karantina_saat", 6.0)
SYMBOL_GUARD_AGIR_ZARAR_ESIK = _pozitif_float_ayar("SYMBOL_GUARD_AGIR_ZARAR_ESIK", "symbol_guard_agir_zarar_esik", 8.0)
SYMBOL_GUARD_AGIR_KARANTINA_SAAT = _pozitif_float_ayar("SYMBOL_GUARD_AGIR_KARANTINA_SAAT", "symbol_guard_agir_karantina_saat", 18.0)
SYMBOL_GUARD_MIN_ZARAR_USDT = _pozitif_float_ayar("SYMBOL_GUARD_MIN_ZARAR_USDT", "symbol_guard_min_zarar_usdt", 1.0)
MAX_LIVE_MARGIN_YUZDESI = _yuzde_ayar("MAX_LIVE_MARGIN_YUZDESI", "max_live_margin_yuzdesi", MAX_LIVE_MARGIN_YUZDESI)
MAX_DEMO_MARGIN_YUZDESI = _yuzde_ayar("MAX_DEMO_MARGIN_YUZDESI", "max_demo_margin_yuzdesi", MAX_DEMO_MARGIN_YUZDESI)
DEMO_MIN_MARGIN_YUZDESI = min(
    MAX_DEMO_MARGIN_YUZDESI,
    _yuzde_ayar("DEMO_MIN_MARGIN_YUZDESI", "demo_min_margin_yuzdesi", DEMO_MIN_MARGIN_YUZDESI),
)
DEMO_DEFANSIF_MARGIN_CARPANI = max(
    0.05,
    min(1.0, _pozitif_float_ayar("DEMO_DEFANSIF_MARGIN_CARPANI", "demo_defansif_margin_carpani", DEMO_DEFANSIF_MARGIN_CARPANI)),
)
HEDEF_POZISYON_RISK_YUZDESI = _yuzde_ayar("HEDEF_POZISYON_RISK_YUZDESI", "hedef_pozisyon_risk_yuzdesi", HEDEF_POZISYON_RISK_YUZDESI)
GUNLUK_ZARAR_LIMITI_AKTIF = _bool_ayar("GUNLUK_ZARAR_LIMITI_AKTIF", "gunluk_zarar_limiti_aktif", True)
GUNLUK_ZARAR_ACIK_POZISYON_DAHIL = _bool_ayar("GUNLUK_ZARAR_ACIK_POZISYON_DAHIL", "gunluk_zarar_acik_pozisyon_dahil", True)
DEMO_GUNLUK_ZARAR_LIMITI_YUZDESI = _yuzde_ayar("DEMO_GUNLUK_ZARAR_LIMITI_YUZDESI", "demo_gunluk_zarar_limiti_yuzdesi", 0.04)
LIVE_GUNLUK_ZARAR_LIMITI_YUZDESI = _yuzde_ayar("LIVE_GUNLUK_ZARAR_LIMITI_YUZDESI", "live_gunluk_zarar_limiti_yuzdesi", 0.02)

MAX_PORTFOY_ISI_YUZDESI = _yuzde_ayar("MAX_PORTFOY_ISI_YUZDESI", "max_portfoy_isi_yuzdesi", 0.25)
MAX_ESANLI_POZISYON = _pozitif_int_ayar("MAX_ESANLI_POZISYON", "max_esanli_pozisyon", 3)
