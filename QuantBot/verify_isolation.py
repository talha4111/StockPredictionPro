"""Verify all borsa_live calls are gated behind LIVE_MOD_AKTIF"""
with open('main.py','r',encoding='utf-8') as f:
    lines = f.readlines()

print('LIVE_MOD_AKTIF referanslari:')
for i,l in enumerate(lines):
    if 'LIVE_MOD_AKTIF' in l:
        print(f'  {i+1}: {l.rstrip()[:100]}')

print()
print('Korunmasiz borsa_live cagrilari:')
tehlikeli = 0
for i,l in enumerate(lines):
    stripped = l.strip()
    if 'borsa_live' in stripped:
        # Skip definitions and comments
        if stripped.startswith('#') or 'borsa_live_config' in stripped or 'borsa_live = ' in stripped:
            continue
        # Check if LIVE_MOD_AKTIF is in surrounding 8 lines
        korunuyor = False
        for j in range(max(0,i-8), i):
            if 'LIVE_MOD_AKTIF' in lines[j]:
                korunuyor = True
                break
        if not korunuyor:
            print(f'  !! KORUNMASIZ: {i+1}: {stripped[:100]}')
            tehlikeli += 1

if tehlikeli == 0:
    print('  TEMIZ - Tum borsa_live cagrilari korunuyor!')
else:
    print(f'\n  UYARI: {tehlikeli} korunmasiz cagri bulundu!')
