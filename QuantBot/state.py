"""
state.py — Sistem çapında global durum sözlüğü (State Container).
Primitive değişkenlerin (int, bool) modüller arasında referansla 
ve güvenli bir şekilde paylaşılmasını sağlar.
"""
from db_logger import _detay_yukle
from datetime import datetime
import threading

bot_state = {
    'borsa': None,
    'borsa_live': None,
    'scout_borsa': None,
    
    'LIVE_MOD_AKTIF': False,
    'ALIM_SATIM_TETIGI_ACIK': False,
    'PING_MODU': False,
    
    'LIVE_ARDISIK_ZARAR': 0,
    'DEMO_ARDISIK_ZARAR': 0,
    
    'KASA_DURUM': {'LIVE_KASA': 0.0, 'DEMO_KASA': 0.0, 'LIVE_EQUITY': 0.0, 'DEMO_EQUITY': 0.0},
    'COOLDOWN_DICT': {},
    'aktif_islemler_detay': _detay_yukle(),
    'SON_ISLEMLER_PNL_DEMO': [],
    'SON_ISLEMLER_PNL_LIVE': [],
    
    '_DEMO_CACHE': {
        'bakiye': 0.0,
        'pozisyonlar': [],
        'son_guncelleme': 0,
        'bakiye_son_guncelleme': 0,
        'bakiye_ozeti': {},
        'muhasebe_ozeti': {},
    },
    'performans': {'kazanc': 0, 'kayip': 0},
    
    'BASLANGIC_SERMAYE_DEMO': 0.0,
    'BASLANGIC_SERMAYE_LIVE': 27.0,
    
    'LIVE_API_KEY': "",
    'LIVE_SECRET': "",
    
    'LIVE_ISLEM_KILIDI': threading.RLock()
}
