import re

with open('QuantBot/main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

start_idx = -1
for i, line in enumerate(lines):
    if line.startswith('def surekli_tarama_ve_analiz('):
        start_idx = i
        break

end_idx = -1
for i in range(start_idx, len(lines)):
    if lines[i].startswith('if __name__ == '):
        end_idx = i
        break

code_lines = lines[start_idx:end_idx]

header = """\"\"\"
scanner_loop.py — Ana Tarama ve Sinyal Koordinasyon Motoru
Sürekli piyasayı tarar, uygun coinleri seçer, analiz motoruna gönderir
ve sinyal üretildiğinde emir motorunu (order_engine) tetikler.
\"\"\"
from datetime import datetime
import time

from config import (
    SPOT_SEMBOLLER, TEK_DONGU_TANI_MODU, MIN_SCOUT_QUOTE_VOLUME_USDT, MAX_SCOUT_COIN_SAYISI,
    TANI_MAX_COIN_SAYISI, DEMO_CALISMA_PROFILI, DEMO_LIVE_SHADOW_AKTIF, SHORT_ISLEM_AKTIF, REF
)
from db_logger import gunluk_rapor_gonder
from signal_engine import analiz_motoru, veri_getir_dortlu, BeyinMotoru
from order_engine import islem_ac

try:
    from runtime_status import status_yaz
except:
    def status_yaz(a, event=None): pass

"""

code_text = ''.join(code_lines)

code_text = code_text.replace('def surekli_tarama_ve_analiz():', 'def surekli_tarama_ve_analiz(ctx):')
code_text = re.sub(r'\s*global\s+.*?\n', '\n', code_text)

# We need to map these globals to ctx
replacements = [
    'SON_RAPOR_ZAMANI_10', 'SON_RAPOR_ZAMANI_22', 'performans', 'KASA_DURUM', '_DEMO_CACHE',
    'KARANTINA_LISTESI', 'LIVE_MOD_AKTIF', 'ALIM_SATIM_TETIGI_ACIK', 'PING_MODU',
    'scout_borsa', 'borsa_live', 'borsa', 'aktif_islemler_detay', 'COOLDOWN_DICT',
    'LIVE_ARDISIK_ZARAR', 'DEMO_ARDISIK_ZARAR', 'SON_ISLEMLER_PNL_DEMO', 'SON_ISLEMLER_PNL_LIVE',
    'LIVE_ISLEM_KILIDI', 'LIVE_API_KEY', 'LIVE_SECRET'
]

for var in replacements:
    code_text = re.sub(r'(?<!ctx\[\')\b' + var + r'\b', f"ctx['{var}']", code_text)

# We must ensure that we don't accidentally do ctx['ctx['var']'] 
for var in replacements:
    code_text = code_text.replace(f"ctx['ctx['{var}']']", f"ctx['{var}']")

with open('QuantBot/scanner_loop.py', 'w', encoding='utf-8') as f:
    f.write(header + code_text)

# Now update main.py to remove it and inject the context dictionary
new_lines = lines[:start_idx] + lines[end_idx:]
main_text = ''.join(new_lines)

if 'from scanner_loop import surekli_tarama_ve_analiz' not in main_text:
    main_text = main_text.replace('from position_tracker import pozisyon_takip_paneli', 'from position_tracker import pozisyon_takip_paneli\nfrom scanner_loop import surekli_tarama_ve_analiz')

# Create ctx inside the while loop if not already present
# Or since main loop relies on surekli_tarama_ve_analiz, modify its calls
ctx_scanner = """
        ctx_scanner = {
            'SON_RAPOR_ZAMANI_10': SON_RAPOR_ZAMANI_10, 'SON_RAPOR_ZAMANI_22': SON_RAPOR_ZAMANI_22,
            'performans': performans, 'KASA_DURUM': KASA_DURUM, '_DEMO_CACHE': _DEMO_CACHE,
            'KARANTINA_LISTESI': KARANTINA_LISTESI, 'LIVE_MOD_AKTIF': LIVE_MOD_AKTIF,
            'ALIM_SATIM_TETIGI_ACIK': ALIM_SATIM_TETIGI_ACIK, 'PING_MODU': PING_MODU,
            'scout_borsa': scout_borsa, 'borsa_live': borsa_live, 'borsa': borsa,
            'aktif_islemler_detay': aktif_islemler_detay, 'COOLDOWN_DICT': COOLDOWN_DICT,
            'LIVE_ARDISIK_ZARAR': LIVE_ARDISIK_ZARAR, 'DEMO_ARDISIK_ZARAR': DEMO_ARDISIK_ZARAR,
            'SON_ISLEMLER_PNL_DEMO': SON_ISLEMLER_PNL_DEMO, 'SON_ISLEMLER_PNL_LIVE': SON_ISLEMLER_PNL_LIVE,
            'LIVE_ISLEM_KILIDI': LIVE_ISLEM_KILIDI, 'LIVE_API_KEY': LIVE_API_KEY, 'LIVE_SECRET': LIVE_SECRET
        }
        surekli_tarama_ve_analiz(ctx_scanner)
        # Update primitives back to main scope (e.g. SON_RAPOR_ZAMANI) if they were changed
        SON_RAPOR_ZAMANI_10 = ctx_scanner['SON_RAPOR_ZAMANI_10']
        SON_RAPOR_ZAMANI_22 = ctx_scanner['SON_RAPOR_ZAMANI_22']
"""
main_text = main_text.replace('surekli_tarama_ve_analiz()', ctx_scanner.strip())

with open('QuantBot/main.py', 'w', encoding='utf-8') as f:
    f.write(main_text)

print('scanner_loop.py yazildi ve main.py guncellendi.')
