with open('QuantBot/scanner_loop.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('CANLI_DEVRE_KESICI_AKTIF', "ctx['CANLI_DEVRE_KESICI_AKTIF']")
text = text.replace("ctx['ctx['CANLI_DEVRE_KESICI_AKTIF']']", "ctx['CANLI_DEVRE_KESICI_AKTIF']")

with open('QuantBot/scanner_loop.py', 'w', encoding='utf-8') as f:
    f.write(text)

with open('QuantBot/main.py', 'r', encoding='utf-8') as f:
    main_text = f.read()

main_text = main_text.replace("'KARANTINA_LISTESI': KARANTINA_LISTESI, ", "'KARANTINA_LISTESI': KARANTINA_LISTESI, 'CANLI_DEVRE_KESICI_AKTIF': CANLI_DEVRE_KESICI_AKTIF, ")

with open('QuantBot/main.py', 'w', encoding='utf-8') as f:
    f.write(main_text)

print('CANLI_DEVRE_KESICI_AKTIF fixed.')
