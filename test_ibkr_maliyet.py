"""ibkr_bridge.py v2.0 Maliyet Motoru + Net RR Filtresi Testi (TWS gerektirmez)"""
from ibkr_bridge import islem_maliyeti_hesapla, net_rr_filtresi

print("=" * 55)
print("  MALIYET MOTORU & NET RR FILTRESI TESTI")
print("=" * 55)

#  TEST 1: AAPL $210, 50 hisse, 3 bps spread
print("\n[TEST 1] AAPL $210 x 50 hisse | Spread: 3 bps")
print("-" * 45)
m = islem_maliyeti_hesapla(210, 50, spread_bps=3)
print(f"  Islem Degeri:    ${m['islem_degeri']:,.2f}")
print(f"  Komisyon (G+C):  ${m['komisyon_toplam']:.2f}")
print(f"  Spread Maliyeti: ${m['spread_maliyet']:.2f}")
print(f"  TOPLAM Maliyet:  ${m['toplam_maliyet']:.2f}")
print(f"  Maliyet/Hisse:   ${m['maliyet_per_hisse']:.4f}")
print(f"  Maliyet Orani:   %{m['maliyet_yuzde']:.3f}")

# TEST 2: Net RR Filtresi — Genis hedef (ONAY bekleniyor)
print(f"\n[TEST 2] Net RR — Genis Hedef: Giris=$210, TP=$220, SL=$203")
print("-" * 45)
r1 = net_rr_filtresi(210, 220, 203, 50, spread_bps=3)
print(f"  Brut Kar: ${r1['brut_kar']:.2f} | Net Kar: ${r1['net_kar']:.2f}")
print(f"  Brut RR: {r1['brut_rr']:.2f}x | Net RR: {r1['net_rr']:.2f}x")
print(f"  Karar: {r1['karar']}")

# TEST 3: Net RR Filtresi — Dar hedef (RED bekleniyor)
print(f"\n[TEST 3] Net RR — Dar Hedef: Giris=$210, TP=$212, SL=$208")
print("-" * 45)
r2 = net_rr_filtresi(210, 212, 208, 50, spread_bps=3)
print(f"  Brut Kar: ${r2['brut_kar']:.2f} | Net Kar: ${r2['net_kar']:.2f}")
print(f"  Brut RR: {r2['brut_rr']:.2f}x | Net RR: {r2['net_rr']:.2f}x")
print(f"  Karar: {r2['karar']}")

# TEST 4: Yuksek spread senaryosu (50 bps — LIKIT OLMAYAN HISSE)
print(f"\n[TEST 4] Dusuk Likidite: $15 hisse x 200 adet | Spread: 50 bps")
print("-" * 45)
m2 = islem_maliyeti_hesapla(15, 200, spread_bps=50)
print(f"  Toplam Maliyet: ${m2['toplam_maliyet']:.2f} (%{m2['maliyet_yuzde']:.3f})")
r3 = net_rr_filtresi(15.0, 16.5, 14.0, 200, spread_bps=50)
print(f"  Net RR: {r3['net_rr']:.2f}x | Karar: {r3['karar']}")

print(f"\n{'=' * 55}")
print("  Tum testler tamamlandi.")
print(f"{'=' * 55}")
