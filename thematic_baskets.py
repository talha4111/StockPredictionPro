"""
THEMATIC BASKETS v1.0 — Tematik Sektör ve Özel Havuz Kütüphanesi
===============================================================
Geleneksel GICS sektör sınıflandırmalarının (Teknoloji, Enerji vb.) ötesinde,
modern yatırım temalarını ve değer zincirlerini gruplayan akıllı havuz modülü.
"""

from typing import Dict, List, Optional

# Önceden Tanımlı Tematik Havuzlar
TEMATIK_HAVUZLAR: Dict[str, Dict[str, object]] = {
    "AI_ENERJI_GUC": {
        "ad": "Yapay Zekayı Besleyen Enerji & Şebeke Altyapısı",
        "aciklama": "AI veri merkezlerinin devasa elektrik ve soğutma ihtiyacını karşılayan nükleer, gaz, trafo ve şebeke hisseleri",
        "semboller": ["CEG", "VST", "GEV", "ETN", "PWR", "NEE", "CCJ", "TLN", "SMR", "OKLO", "SO", "DUK"],
        "odak_alanlari": {
            "CEG": "Nükleer Santral Üreticisi (Microsoft PPA Anlaşmalı)",
            "VST": "Toptan Nükleer & Doğalgaz Elektrik Üretimi",
            "GEV": "Gaz Türbinleri, Şebeke Elektrifikasyonu & Trafo",
            "ETN": "Veri Merkezi Güç Yönetimi, Kesintisiz Güç & Şalt Donanımı",
            "PWR": "Yüksek Gerilim İletim Hatları & Altyapı İnşaatı",
            "NEE": "Temiz Enerji / Kamu Hizmeti & Nükleer Portföy",
            "CCJ": "Uranyum Yakıt Madenciliği & Dönüştürme",
            "TLN": "Nükleer Santralden Doğrudan Veri Merkezine Güç (AWS)",
            "SMR": "Küçük Modüler Reaktörler (NuScale Power)",
            "OKLO": "Yeni Nesil Hızlı Fisyon Reaktörleri (Sam Altman Destekli)",
            "SO": "Büyük Ölçekli Nükleer ve Şebeke Altyapısı (Vogtle Santrali)",
            "DUK": "Güneydoğu ABD Veri Merkezi Enerji Altyapısı",
        }
    },
    "YARI_ILETKEN_EKIPMAN": {
        "ad": "Yarı İletken ve Çip Üretim Ekipmanları (Pick & Shovel)",
        "aciklama": "Çip fabrikalarına fotolitografi, aşındırma ve test ekipmanı sağlayan tekel üreticiler",
        "semboller": ["ASML", "AMAT", "LRCX", "KLAC", "TSM", "CAMT", "ONTO", "MKSI"],
        "odak_alanlari": {
            "ASML": "EUV & DUV Fotolitografi Tekeli",
            "AMAT": "Malzeme Mühendisliği ve Yarı İletken Üretim Sistemleri",
            "LRCX": "Gelişmiş Aşındırma (Etch) ve İnce Film Kaplama (Deposition)",
            "KLAC": "Yarı İletken Hata Tespit ve Süreç Kontrol Cihazları",
            "TSM": "Dünyanın En Büyük Bağımsız Yarı İletken Dökümhanesi (Foundry)",
            "CAMT": "Gelişmiş Paketleme (Advanced Packaging) Optik Denetim",
        }
    },
    "VERI_MERKEZI_ALTYAPI": {
        "ad": "Yapay Zeka Donanımı & Veri Merkezi Altyapısı",
        "aciklama": "Sunucu, yüksek hızlı optik ağ anahtarları ve sıvı soğutma sistemleri",
        "semboller": ["NVDA", "AVGO", "ANET", "VRT", "DELL", "SMCI", "MRVL", "CSCO"],
        "odak_alanlari": {
            "NVDA": "AI Hızlandırıcı GPU & CUDA Platformu Lideri",
            "AVGO": "Özel ASIC Çipler, Optik Bağlantılar & Ağ Çözümleri",
            "ANET": "Yüksek Hızlı Veri Merkezi Ağ Anahtarları (Cloud Networking)",
            "VRT": "Veri Merkezi Sıvı Soğutma ve Güç Sürekliliği Sistemleri",
            "DELL": "Kurumsal AI Sunucu Çözümleri ve Dağıtık Altyapı",
            "SMCI": "Yüksek Yoğunluklu Sıvı Soğutmalı Sunucu Mimarileri",
            "MRVL": "Optik DSP ve Özel Veri Merkezi Silikon Çözümleri",
        }
    },
    "SAVUNMA_VE_HAVACILIK": {
        "ad": "Savunma Sanayi, Füze & Askeri Havacılık",
        "aciklama": "Jeopolitik gerilimler ve NATO bütçe artışlarından beslenen savunma devleri",
        "semboller": ["LMT", "RTX", "NOC", "GD", "BA", "KTOS", "HII", "LHX"],
        "odak_alanlari": {
            "LMT": "F-35 Savaş Uçağı, HIMARS ve Hava Savunma Sistemleri",
            "RTX": "Patriot Hava Savunma ve Pratt & Whitney Uçak Motorları",
            "NOC": "B-21 Hayalet Bombardıman ve Uzay Savunma Sistemleri",
            "GD": "Nükleer Denizaltılar ve Kara Muharebe Araçları",
            "BA": "Ticari Havacılık ve Askeri Taşıma Uçakları",
            "KTOS": "Otonom Savaş İHA'ları ve Uydu İletişim Güvenliği",
        }
    },
    "SIBER_GUVENLIK": {
        "ad": "Yeni Nesil Bulut & Kurumsal Siber Güvenlik",
        "aciklama": "Yapay zeka destekli uç nokta koruması ve Zero-Trust ağ güvenliği",
        "semboller": ["PANW", "CRWD", "FTNT", "ZS", "NET", "CHKP", "OKTA"],
        "odak_alanlari": {
            "PANW": "Yeni Nesil Güvenlik Duvarı ve Prisma Bulut Platformu",
            "CRWD": "Yapay Zeka Destekli Uç Nokta Koruması (Falcon Platformu)",
            "FTNT": "Entegre Ağ Güvenliği ve Özel Güvenlik Çipleri (FortiASIC)",
            "ZS": "Bulut Tabanlı Sıfır Güven (Zero-Trust) Değişim Mimarisi",
            "NET": "DDoS Koruması, Küresel CDN ve Uç Bilişim Güvenliği",
        }
    },
    "SAGLIK_VE_GLP1": {
        "ad": "Biyoteknoloji, GLP-1 (Obezite) & Tıbbi Robotik",
        "aciklama": "Obezite ilaçları devrimi ve cerrahi robotik teknolojisi",
        "semboller": ["LLY", "NVO", "ISRG", "AMGN", "VRTX", "ABBV", "REGN"],
        "odak_alanlari": {
            "LLY": "Tirzepatide (Mounjaro/Zepbound) GLP-1/GIP Lideri",
            "NVO": "Semaglutide (Ozempic/Wegovy) GLP-1 Öncüsü",
            "ISRG": "da Vinci Robotik Cerrahi Sistemleri Tekeli",
            "VRTX": "Kistik Fibrozis ve Gen Düzenleme Tedavileri (CRISPR)",
        }
    }
}


def tema_getir(tema_kodu_veya_adi: str) -> Optional[Dict[str, object]]:
    """
    Belirtilen tema adına veya koduna göre havuz detaylarını döner.
    Küçük harf, boşluk ve tire toleranslıdır.
    """
    hedef = tema_kodu_veya_adi.strip().upper().replace(" ", "_").replace("-", "_")
    
    # Doğrudan anahtar kontrolü
    if hedef in TEMATIK_HAVUZLAR:
        return TEMATIK_HAVUZLAR[hedef]
        
    # Kısmi eşleşme kontrolü (örn: 'ai_enerji' -> 'AI_ENERJI_GUC')
    for key, val in TEMATIK_HAVUZLAR.items():
        if hedef in key or key in hedef:
            return val
        if hedef.lower() in str(val.get("ad", "")).lower():
            return val
            
    return None


def tum_temalar() -> Dict[str, str]:
    """Sistemde kayıtlı tüm temaların kodunu ve adını döner."""
    return {k: str(v["ad"]) for k, v in TEMATIK_HAVUZLAR.items()}


def ozel_sepet_olustur(semboller: List[str], sepet_adi: str = "ÖZEL_SEPET") -> Dict[str, object]:
    """Kullanıcının dinamik olarak sağladığı sembollerden geçici sepet oluşturur."""
    temiz_semboller = [s.strip().upper() for s in semboller if s.strip()]
    return {
        "ad": sepet_adi,
        "aciklama": f"Kullanıcı tanımlı özel sepet ({len(temiz_semboller)} sembol)",
        "semboller": temiz_semboller,
        "odak_alanlari": {}
    }


if __name__ == "__main__":
    print("=== KAYITLI TEMATİK HAVUZLAR ===")
    for kod, ad in tum_temalar().items():
        detay = tema_getir(kod)
        semboller = detay.get("semboller", []) if detay else []
        print(f"[{kod}] -> {ad} ({len(semboller)} Hisse: {', '.join(semboller[:6])}...)")
