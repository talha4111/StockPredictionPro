import re

with open('QuantBot/main.py', 'r', encoding='utf-8') as f:
    text = f.read()

bad_block = """
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
        SON_RAPOR_ZAMANI_22 = ctx_scanner['SON_RAPOR_ZAMANI_22']"""

good_block = bad_block.replace('\n        ', '\n            ')

text = text.replace(bad_block, good_block)

with open('QuantBot/main.py', 'w', encoding='utf-8') as f:
    f.write(text)

print('Indentation fixed.')
