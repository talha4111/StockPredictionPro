import optuna
import warnings
import os
from crypto_backtest import backtest_calistir

# Veritabanı dosyası — Optuna tüm denemeleri buraya kaydeder.
# Ctrl+C ile durdursan bile, tekrar çalıştırdığında kaldığı yerden devam eder.
DB_PATH = os.path.join(os.path.dirname(__file__), "optuna_study.db")
STUDY_NAME = "quantbot_xgboost_cost_aware_v2"

def objective(trial):
    n_est = trial.suggest_int("n_estimators", 50, 500, step=50)
    m_depth = trial.suggest_int("max_depth", 3, 10)
    
    params = {"n_estimators": n_est, "max_depth": m_depth}
    print(f"\n🔄 Optuna Test Ediyor -> Ağaç(Trees): {n_est}, Derinlik(Depth): {m_depth}")
    
    sonuc = backtest_calistir(params)
    
    if sonuc['total_trades'] < 3:
        print(f"   => Çok az işlem yaptı ({sonuc['total_trades']}). Cezalandırılıyor.")
        return -9999.0
        
    print(f"   => İşlem: {sonuc['total_trades']} | Başarı: %{sonuc['win_rate']:.1f} | K/Z: {sonuc['pnl']:+,.2f} USDT")
    return sonuc['pnl']

if __name__ == "__main__":
    warnings.filterwarnings('ignore')
    optuna.logging.set_verbosity(optuna.logging.INFO)
    
    storage = f"sqlite:///{DB_PATH}"
    
    # Mevcut study varsa yükle (kaldığı yerden devam), yoksa yeni oluştur
    try:
        study = optuna.load_study(study_name=STUDY_NAME, storage=storage)
        tamamlanan = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
        print("=" * 70)
        print("🧠 OPTUNA — KALDIĞI YERDEN DEVAM EDİYOR")
        print("=" * 70)
        print(f"📂 Veritabanı: {DB_PATH}")
        print(f"✅ Daha önce tamamlanan deneme: {tamamlanan}")
        if tamamlanan > 0:
            print(f"🏆 Şu anki en iyi sonuç: {study.best_value:+,.2f} USDT")
            bp = study.best_params
            print(f"   Ağaç: {bp['n_estimators']} | Derinlik: {bp['max_depth']}")
        print(f"🔄 Kalan deneme: {max(0, 30 - tamamlanan)}")
    except KeyError:
        study = optuna.create_study(study_name=STUDY_NAME, storage=storage, direction="maximize")
        print("=" * 70)
        print("🧠 OPTUNA — YENİ OPTİMİZASYON BAŞLATILIYOR")
        print("=" * 70)
        print(f"📂 Veritabanı: {DB_PATH}")
        print("🎯 Hedef: 30 akıllı deneme")
    
    print("⏹️  İstediğin zaman Ctrl+C ile durdurabilirsin, kaldığı yerden devam eder.\n")
    
    tamamlanan = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
    kalan = max(0, 30 - tamamlanan)
    
    if kalan == 0:
        print("✅ 30 denemenin tamamı zaten bitirilmiş!")
    else:
        try:
            study.optimize(objective, n_trials=kalan)
        except KeyboardInterrupt:
            print("\n⏹️ Test durduruldu. Sonuçlar veritabanına kaydedildi.")
        
    print("\n" + "=" * 70)
    print("🏆 OPTUNA OPTİMİZASYON SONUCU: EN İYİ MODEL")
    print("=" * 70)
    
    tamamlanan = len([t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE])
    
    try:
        best = study.best_trial
        print(f"✅ Tavsiye Edilen n_estimators : {best.params['n_estimators']}")
        print(f"✅ Tavsiye Edilen max_depth    : {best.params['max_depth']}")
        print("-" * 70)
        print(f"💰 Beklenen Sanal K/Z Net       : {best.value:+,.2f} USDT")
        print(f"📊 Toplam tamamlanan deneme     : {tamamlanan}/30")
        print("=" * 70)
    except Exception:
        print("Henüz yeterli deneme tamamlanmadı.")
    
    print(f"\n💾 Tüm sonuçlar kayıtlı: {DB_PATH}")
    print("   Tekrar çalıştırırsan kaldığı yerden devam eder.")
