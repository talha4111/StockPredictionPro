import os

with open('QuantBot/config.py', 'a', encoding='utf-8') as f:
    f.write("\nMAX_PORTFOY_ISI_YUZDESI = 0.30\n")
    f.write("MAX_ESANLI_POZISYON = 10\n")

with open('QuantBot/scanner_loop.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Imports
text = text.replace('from config import (', 'from config import (\n    MAX_PORTFOY_ISI_YUZDESI, MAX_ESANLI_POZISYON, SEKTORLER,')
text = text.replace('from risk_manager import process_demo_exit_rules', '')
text = text.replace('from signal_engine import analiz_motoru', 'from signal_engine import analiz_motoru\nfrom risk_manager import _sinyal_darbogaz_ozeti, SINYAL_RET_ISTATISTIKLERI\nfrom demo_trade_journal import rapor_kaydet as demo_rapor_kaydet, dispatch_ret_kaydet as demo_dispatch_ret_kaydet, journal_status_guncelle as demo_journal_status_guncelle')

# Replacements
text = text.replace('COIN_ZARAR_SAYACI', "ctx['COIN_ZARAR_SAYACI']")
text = text.replace('KARA_LISTE', "ctx['KARA_LISTE']")
text = text.replace('onceki_pozisyonlar', "ctx['onceki_pozisyonlar']")
text = text.replace('borsa_baglantisini_yenile(', "ctx['borsa_baglantisini_yenile'](")

# Remove potential duplicate string creations like ctx['ctx['...']']
text = text.replace("ctx['ctx['COIN_ZARAR_SAYACI']']", "ctx['COIN_ZARAR_SAYACI']")
text = text.replace("ctx['ctx['KARA_LISTE']']", "ctx['KARA_LISTE']")
text = text.replace("ctx['ctx['onceki_pozisyonlar']']", "ctx['onceki_pozisyonlar']")

with open('QuantBot/scanner_loop.py', 'w', encoding='utf-8') as f:
    f.write(text)

with open('QuantBot/main.py', 'r', encoding='utf-8') as f:
    main_text = f.read()

main_text = main_text.replace("'CANLI_DEVRE_KESICI_AKTIF': CANLI_DEVRE_KESICI_AKTIF,", "'CANLI_DEVRE_KESICI_AKTIF': CANLI_DEVRE_KESICI_AKTIF, 'COIN_ZARAR_SAYACI': COIN_ZARAR_SAYACI, 'KARA_LISTE': KARA_LISTE, 'borsa_baglantisini_yenile': borsa_baglantisini_yenile,")

with open('QuantBot/main.py', 'w', encoding='utf-8') as f:
    f.write(main_text)

print('Patch completed.')
