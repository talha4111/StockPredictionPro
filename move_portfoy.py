import re

with open('QuantBot/main.py', 'r', encoding='utf-8') as f:
    main_text = f.read()

match = re.search(r'def portfoy_isi_hesapla\(\):.*?return .*?\n\n', main_text, re.DOTALL)
if match:
    func_text = match.group(0)
    
    with open('QuantBot/scanner_loop.py', 'r', encoding='utf-8') as f:
        scanner_text = f.read()
    
    new_func = func_text.replace('def portfoy_isi_hesapla():', 'def portfoy_isi_hesapla(ctx, _BU_TUR_ACILAN):')
    new_func = new_func.replace('_DEMO_CACHE', "ctx['_DEMO_CACHE']")
    new_func = new_func.replace('KASA_DURUM', "ctx['KASA_DURUM']")
    
    scanner_text = scanner_text.replace('def surekli_tarama_ve_analiz(ctx):', new_func + '\ndef surekli_tarama_ve_analiz(ctx):')
    scanner_text = scanner_text.replace('portfoy_isi_hesapla()', 'portfoy_isi_hesapla(ctx, _BU_TUR_ACILAN)')
    
    with open('QuantBot/scanner_loop.py', 'w', encoding='utf-8') as f:
        f.write(scanner_text)
        
    main_text = main_text.replace(func_text, '')
    with open('QuantBot/main.py', 'w', encoding='utf-8') as f:
        f.write(main_text)
        
    print('portfoy_isi_hesapla moved.')
else:
    print('Function not found')
