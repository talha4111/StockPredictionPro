from transformers import BertTokenizer, BertForSequenceClassification, pipeline

class NewsAnalyzer:
    def __init__(self):
        # Model yüklenirken kullanıcıyı bilgilendir
        print("🧠 FinBERT Modeli Yükleniyor...")
        model_name = "yiyanghkust/finbert-tone"
        
        try:
            self.tokenizer = BertTokenizer.from_pretrained(model_name)
            self.model = BertForSequenceClassification.from_pretrained(model_name)
            self.nlp = pipeline("sentiment-analysis", model=self.model, tokenizer=self.tokenizer)
        except Exception as e:
            print(f"❌ Model Yükleme Hatası: {e}")
            self.nlp = None

    def get_sentiment_score(self, text):
        """
        Metni puanlar. Debug için arka planda print alır.
        """
        if not self.nlp or not text:
            return 0.0

        try:
            # 1. FinBERT Analizi
            result = self.nlp(text[:512])[0] 
            label = result['label']
            score = result['score']

            # DEBUG: Bakalım yapay zeka ham olarak ne diyor?
            # (Bunu normalde kapatabilirsin ama şimdilik görelim)
            # print(f"   [DEBUG] AI Kararı: {label} ({score:.4f}) -> {text[:30]}...")

            final_score = 0.0
            if label == "Positive":
                final_score = score
            elif label == "Negative":
                final_score = -score
            else:
                final_score = 0.0 # Neutral

            # ---------------------------------------------------------
            # 2. HİBRİT KONTROL (Genişletilmiş Kelime Listesi)
            # ---------------------------------------------------------
            
            # Eğer AI "Nötr" dediyse veya puan düşükse müdahale et
            if -0.5 < final_score < 0.5:
                text_lower = text.lower()
                
                # KÖTÜ KELİMELER (Genişletildi)
                bad_words = [
                    "falling", "plunge", "crash", "drop", "down", "bearish", 
                    "sell", "lower", "loss", "missed", "weak", "concern", "risk",
                    "slips", "slides", "tumbles", "cuts", "negative", "warns",
                    "halt", "investigation", "lawsuit"
                ]
                
                # İYİ KELİMELER (Genişletildi)
                good_words = [
                    "soar", "jump", "rise", "surge", "bullish", "buy", 
                    "record", "gain", "profit", "beat", "strong", "growth",
                    "wins", "deal", "partnership", "agreement", "upgrade", 
                    "positive", "higher", "climb", "ties up", "lands"
                ]

                # Kelime kontrolü
                for word in bad_words:
                    if word in text_lower:
                        return -0.85 # Negatif Zorla

                for word in good_words:
                    if word in text_lower:
                        return 0.85 # Pozitif Zorla

            return final_score
                
        except Exception as e:
            print(f"Sentiment Hatası: {e}")
            return 0.0

if __name__ == "__main__":
    analist = NewsAnalyzer()
    test_text = "Boeing Stock Slips Despite Advancing Deal"
    print(f"Test Puanı: {analist.get_sentiment_score(test_text)}")