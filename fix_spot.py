with open('QuantBot/scanner_loop.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('SPOT_SEMBOLLER, ', '')
text = text.replace('SPOT_SEMBOLLER', "ctx['SPOT_SEMBOLLER']")

with open('QuantBot/scanner_loop.py', 'w', encoding='utf-8') as f:
    f.write(text)

with open('QuantBot/main.py', 'r', encoding='utf-8') as f:
    main_text = f.read()

main_text = main_text.replace("'LIVE_SECRET': LIVE_SECRET", "'LIVE_SECRET': LIVE_SECRET, 'SPOT_SEMBOLLER': SPOT_SEMBOLLER")

with open('QuantBot/main.py', 'w', encoding='utf-8') as f:
    f.write(main_text)

print('SPOT_SEMBOLLER fixed.')
