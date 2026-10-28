import numpy as np
import pandas as pd
import joblib
import json
import math
import os
import tempfile
from model_contract import (
    FeatureAvailabilitySpec,
    FeatureCoverageSpec,
    OutcomeSpec,
    PurgedWalkForwardSpec,
)

class BeyinMotoru:
    def __init__(
        self,
        n_estimators=200,
        max_depth=4,
        model_prefix=None,
        label_schema_version=5,
        base_timeframe="4h",
    ):
        try:
            self.label_schema_version = int(label_schema_version)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Geçersiz label schema version: {label_schema_version!r}"
            ) from exc
        if self.label_schema_version not in (5, 6):
            raise ValueError(
                f"Desteklenmeyen label schema version: {self.label_schema_version}; "
                "izin verilenler: 5, 6"
            )
        self.base_timeframe = str(base_timeframe or "4h")
        # Optuna window validation winner (2026-07-11): 450 trees, depth 8.
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_split = 20
        self.min_samples_leaf = 10
        self.random_state = 42
        varsayilan_prefix = (
            "v6_beyin" if self.label_schema_version == 6 else "beyin"
        )
        self.model_prefix = (
            varsayilan_prefix if model_prefix is None else str(model_prefix)
        )
        # v5: Taker_Ratio ve BTC_Korelasyon ile 30 -> 32 feature.
        self.model_schema_version = self.label_schema_version
        self.horizon_bars = 6
        self.min_target_return = 0.025
        self.signal_threshold = 0.60
        self.round_trip_cost_rate = 0.001
        self.v6_artifact_quality_thresholds = (
            {
                "min_balanced_accuracy": 0.52,
                "max_brier_score": 0.26,
                "min_brier_skill": 0.001,
                "min_recent_signal_count": 8,
                "min_recent_net_return": 0.0,
                "min_recent_profit_factor": 1.10,
            }
            if self.label_schema_version == 6
            else None
        )
        self.outcome_spec = (
            OutcomeSpec(
                schema_version=6,
                horizon_bars=self.horizon_bars,
                round_trip_cost_rate=self.round_trip_cost_rate,
                minimum_edge_rate=(
                    self.min_target_return - self.round_trip_cost_rate
                ),
            )
            if self.label_schema_version == 6
            else None
        )
        self.training_split_spec = (
            PurgedWalkForwardSpec(
                schema_version=6,
                base_timeframe=self.base_timeframe,
                horizon_bars=self.horizon_bars,
                purge_bars=self.horizon_bars,
                embargo_bars=1,
                n_splits=3,
                min_train_bars=500,
                min_train_fraction=0.40,
                min_validation_bars=20,
            )
            if self.label_schema_version == 6
            else None
        )
        self.feature_availability_spec = (
            FeatureAvailabilitySpec(
                schema_version=6,
                base_timeframe=self.base_timeframe,
            )
            if self.label_schema_version == 6
            else None
        )
        min_joint = 1000 if self.base_timeframe == "15m" else 2000
        self.feature_coverage_spec = (
            FeatureCoverageSpec(
                schema_version=6,
                base_timeframe=self.base_timeframe,
                min_joint_available_bars=min_joint,
            )
            if self.label_schema_version == 6
            else None
        )
        
        # Kullanılacak Özellik Sütunları (Sadece GERÇEK verİ — sahte/sabit değerler çıkarıldı)
        self.stock_features = ['Hedef_Ret', 'Ref_Ret', 'RSI', 'ADX', 'EMA_Slope', 'Vol_Ret', 'BB_Width', 'VP_Sapma']
        # Core 10 feature — gürültü azaltılmış, permutation importance bazlı seçim
        self.crypto_features = [
            'RSI', 'ADX', 'EMA_Slope', 'Volume_ZScore', 'ATR_ZScore',
            'Funding_Rate', 'Buy_Pressure', 'Trend_Alignment',
            'Hedef_Ret', 'VP_Sapma',
        ]
        if self.label_schema_version == 6:
            self.crypto_features += [
                'Open_Interest_Available',
                'Open_Interest_Age_Bars',
                'Funding_Rate_Available',
                'Funding_Rate_Age_Bars',
            ]
        self.son_tahmin_aciklama = {}
        self.son_egitim_meta = {}

    @staticmethod
    def _atomik_model_kaydet(model, hedef):
        hedef = os.path.abspath(hedef)
        klasor = os.path.dirname(hedef)
        fd, gecici = tempfile.mkstemp(
            prefix=os.path.basename(hedef) + ".",
            suffix=".tmp",
            dir=klasor,
        )
        os.close(fd)
        try:
            joblib.dump(model, gecici)
            os.replace(gecici, hedef)
        finally:
            if os.path.exists(gecici):
                os.remove(gecici)

    @staticmethod
    def _atomik_json_kaydet(veri, hedef):
        hedef = os.path.abspath(hedef)
        klasor = os.path.dirname(hedef)
        fd, gecici = tempfile.mkstemp(
            prefix=os.path.basename(hedef) + ".",
            suffix=".tmp",
            dir=klasor,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as dosya:
                json.dump(veri, dosya, ensure_ascii=False)
                dosya.flush()
                os.fsync(dosya.fileno())
            os.replace(gecici, hedef)
        finally:
            if os.path.exists(gecici):
                os.remove(gecici)

    def _featureleri_dogrula(self, df, aktif_features, hedef_gerekli=False):
        eksik = [f for f in aktif_features if f not in df.columns]
        if eksik:
            raise ValueError(f"Eksik feature kolonları: {eksik}")

        temiz = df.copy()
        gerekli_kolonlar = list(aktif_features)
        if hedef_gerekli:
            gerekli_kolonlar.append('Hedef_Yön')

        for kolon in gerekli_kolonlar:
            temiz[kolon] = pd.to_numeric(temiz[kolon], errors='coerce')

        temiz.replace([np.inf, -np.inf], np.nan, inplace=True)
        temiz.dropna(subset=gerekli_kolonlar, inplace=True)
        return temiz

    def _tahmin_aciklamasi_olustur(self, sembol, model, aktif_features, giris_df, olasilik, model_adi):
        top_features = []
        try:
            importances = getattr(model, 'feature_importances_', None)
            if importances is not None:
                sirali = sorted(zip(aktif_features, importances), key=lambda x: x[1], reverse=True)[:5]
                for ad, etki in sirali:
                    top_features.append({
                        'ad': ad,
                        'etki': float(etki),
                        'deger': float(giris_df.iloc[0][ad])
                    })
        except Exception:
            top_features = []

        self.son_tahmin_aciklama[sembol] = {
            'model': model_adi,
            'olasilik': float(olasilik),
            'top_features': top_features
        }

    def df_hazirla(self, df, drop_neutral=False):
        """
        Gelen ham DataFrame'i (Kripto veya Hisse) modelin anlayacağı eğitim formatına çevirir.
        Geleceği (1 saat / 4 mum sonrası) tahmin eden hedef değişkenini (Y) üretir.
        """
        # Hisselerde "Hedef_Close", "Ref_Ret" gibi isimlendirmeler olmayabilir, eksikleri tamamla
        if 'Hedef_Close' not in df.columns and 'Close' in df.columns:
            df['Hedef_Close'] = df['Close']
        if 'Hedef_Ret' not in df.columns:
            df['Hedef_Ret'] = df['Hedef_Close'].pct_change()
        if 'Ref_Ret' not in df.columns:
            df['Ref_Ret'] = 0.0 # Hisselerde referans coin yoksa 0 (Nötr) geç
        if 'Vol_Ret' not in df.columns and 'Volume' in df.columns:
            df['Vol_Ret'] = df['Volume'].pct_change()
        if 'Korelasyon' not in df.columns:
            df['Korelasyon'] = 0.0
        if 'Kriz' not in df.columns:
            df['Kriz'] = 0.0 
        if 'ADX' not in df.columns:
            df['ADX'] = 25.0  # Nötr ADX değeri
        if 'EMA_Slope' not in df.columns:
            df['EMA_Slope'] = 0.0  # Nötr trend
            
        # Kripto Özel Metrikler (Eksikse Baseline Doldurur)
        if 'Open_Interest' not in df.columns: df['Open_Interest'] = 0.0
        if 'Funding_Rate' not in df.columns: df['Funding_Rate'] = 0.0001
        if self.label_schema_version == 6:
            if 'Open_Interest_Available' not in df.columns:
                df['Open_Interest_Available'] = 0
            if 'Open_Interest_Age_Bars' not in df.columns:
                df['Open_Interest_Age_Bars'] = 3.0
            if 'Funding_Rate_Available' not in df.columns:
                df['Funding_Rate_Available'] = 0
            if 'Funding_Rate_Age_Bars' not in df.columns:
                df['Funding_Rate_Age_Bars'] = 37.0
        if 'CHOP' not in df.columns: df['CHOP'] = 50.0
        if 'Squeeze_ON' not in df.columns: df['Squeeze_ON'] = 0.0
        if 'ATR_ZScore' not in df.columns: df['ATR_ZScore'] = 0.0
        if 'Buy_Pressure' not in df.columns: df['Buy_Pressure'] = 0.0
        if 'Funding_Delta' not in df.columns: df['Funding_Delta'] = 0.0
        if 'Hour_Sin' not in df.columns: df['Hour_Sin'] = 0.0
        if 'Hour_Cos' not in df.columns: df['Hour_Cos'] = 0.0
        # Sprint 1: Multi-Timeframe features
        if 'RSI_1H' not in df.columns: df['RSI_1H'] = 50.0
        if 'EMA_Slope_1H' not in df.columns: df['EMA_Slope_1H'] = 0.0
        if 'ADX_4H' not in df.columns: df['ADX_4H'] = 25.0
        if 'Volume_Trend_4H' not in df.columns: df['Volume_Trend_4H'] = 0.0
        if 'Trend_Alignment' not in df.columns: df['Trend_Alignment'] = 0.0
        # Sprint 3: Order Book Imbalance
        if 'OB_Imbalance' not in df.columns: df['OB_Imbalance'] = 0.0
        
        # Aşama 6: Taker Ratio ve BTC Korelasyonu
        if 'Taker_Ratio' not in df.columns: df['Taker_Ratio'] = 0.5
        if 'BTC_Korelasyon' not in df.columns: df['BTC_Korelasyon'] = 0.0

        if self.label_schema_version == 6:
            if drop_neutral:
                raise ValueError(
                    "V6 outcome sözleşmesi nötr/negatif örnekleri düşürmez; "
                    "drop_neutral=False kullanılmalıdır."
                )
            outcomes = self.outcome_spec.build_long_outcomes(
                df,
                open_column='open',
                close_column='Hedef_Close',
            )
            df['Hedef_Yön'] = outcomes['y_long']
            df['Gelecek_Ret'] = outcomes['gross_return']
            df['Gelecek_Net_Ret'] = outcomes['net_return']
            df['Outcome_Entry'] = outcomes['entry_price']
            df['Outcome_Exit'] = outcomes['exit_price']

            outcome_kolonlari = [
                'Hedef_Yön',
                'Gelecek_Ret',
                'Gelecek_Net_Ret',
                'Outcome_Entry',
                'Outcome_Exit',
            ]
            df.replace([np.inf, -np.inf], np.nan, inplace=True)
            df.dropna(subset=outcome_kolonlari, inplace=True)
            df['Hedef_Yön'] = df['Hedef_Yön'].astype(int)
            return df

        # ============================================================
        # AŞAMA 4: Triple-Barrier Labeling (Vektörel/Numpy Optimizasyonlu)
        # ============================================================
        tp_ret = self.min_target_return
        sl_ret = -self.min_target_return # Simetrik zarar kes
        
        kapanislar = df['Hedef_Close'].values
        n = len(kapanislar)
        yonler = np.full(n, np.nan)
        gercek_getiriler = np.full(n, np.nan)
        
        for i in range(n - self.horizon_bars):
            giris = kapanislar[i]
            if giris <= 0 or np.isnan(giris):
                continue
                
            for j in range(1, self.horizon_bars + 1):
                anlik_getiri = (kapanislar[i+j] - giris) / giris
                # Önce stop-loss kontrolü (daha güvenli/kötümser yaklaşım)
                if anlik_getiri <= sl_ret:
                    yonler[i] = 0
                    gercek_getiriler[i] = anlik_getiri
                    break
                elif anlik_getiri >= tp_ret:
                    yonler[i] = 1
                    gercek_getiriler[i] = anlik_getiri
                    break
                    
            # Zaman bariyerini aştıysa (süre sonuna kadar ne SL ne TP değmediyse)
            # Bu belirsiz piyasa hareketlerini (gürültü) eğitimden çıkarıyoruz (NaN kalır).
            
        df['Hedef_Yön'] = yonler
        df['Gelecek_Ret'] = gercek_getiriler
        
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.dropna(subset=['Hedef_Yön', 'Gelecek_Ret'], inplace=True)
        df['Hedef_Yön'] = df['Hedef_Yön'].astype(int)
        
        return df

    def v6_egitim_plani_hazirla(self, df, holdout_observations=None):
        """Artefakt üretmeden kronolojik v6 CV/holdout sınırlarını hazırlar."""
        if self.label_schema_version != 6:
            raise RuntimeError("V6 eğitim planı yalnızca label schema 6 içindir.")
        if not isinstance(df, pd.DataFrame):
            raise TypeError("df pandas DataFrame olmalıdır.")

        timeline = self.training_split_spec.validate_index(df.index)
        kullanilabilir_outcome = max(0, len(timeline) - self.horizon_bars)
        if holdout_observations is None:
            holdout_observations = min(
                200,
                max(80, kullanilabilir_outcome // 4),
            )
        try:
            holdout_observations = int(holdout_observations)
        except (TypeError, ValueError) as exc:
            raise ValueError("holdout_observations tam sayı olmalıdır.") from exc
        if holdout_observations < self.training_split_spec.min_validation_bars:
            raise ValueError("holdout_observations minimum doğrulama boyundan kısa.")

        # Son horizon satırı outcome üretmez. İstenen holdout gözlem sayısını
        # korumak için ham holdout zaman penceresine bu bilinmeyen kuyruk eklenir.
        raw_holdout_bars = holdout_observations + self.horizon_bars
        planned_holdout = self.training_split_spec.holdout_split(
            timeline,
            holdout_bars=raw_holdout_bars,
        )
        planned_cv_folds = self.training_split_spec.walk_forward_splits(
            planned_holdout.train_index
        )

        prepared = self.df_hazirla(df.copy(), drop_neutral=False)
        eligible_index = pd.DatetimeIndex(prepared.index)
        effective_holdout = planned_holdout.select_eligible(eligible_index)
        effective_cv_folds = tuple(
            fold.select_eligible(eligible_index)
            for fold in planned_cv_folds
        )

        if len(effective_holdout.validation_index) != holdout_observations:
            raise ValueError(
                "V6 holdout outcome kapsamı eksik: "
                f"{len(effective_holdout.validation_index)}/"
                f"{holdout_observations}"
            )
        for fold_number, fold in enumerate(effective_cv_folds, start=1):
            if len(fold.train_index) < self.training_split_spec.min_train_bars:
                raise ValueError(
                    f"V6 CV fold {fold_number} eğitim kapsamı minimumdan kısa."
                )
            if (
                len(fold.validation_index)
                < self.training_split_spec.min_validation_bars
            ):
                raise ValueError(
                    f"V6 CV fold {fold_number} doğrulama kapsamı minimumdan kısa."
                )

        return {
            "outcome_contract_id": self.outcome_spec.contract_id,
            "split_contract_id": self.training_split_spec.contract_id,
            "timeline_index": timeline,
            "eligible_index": eligible_index,
            "holdout_observations": holdout_observations,
            "raw_holdout_bars": raw_holdout_bars,
            "planned_holdout": planned_holdout,
            "holdout": effective_holdout,
            "planned_cv_folds": planned_cv_folds,
            "cv_folds": effective_cv_folds,
        }

    @staticmethod
    def _logit(probability):
        p = np.clip(np.asarray(probability, dtype=float), 1e-6, 1.0 - 1e-6)
        return np.log(p / (1.0 - p))

    @staticmethod
    def _kalibrasyon_uygula(probability, katsayi, sabit):
        logits = BeyinMotoru._logit(probability)
        z = np.clip((float(katsayi) * logits) + float(sabit), -30.0, 30.0)
        return 1.0 / (1.0 + np.exp(-z))

    def _strateji_metrikleri(
        self,
        probabilities,
        future_returns,
        *,
        returns_are_net=False,
        signal_threshold=None,
    ):
        threshold = (
            self.signal_threshold
            if signal_threshold is None
            else float(signal_threshold)
        )
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("signal_threshold [0, 1] aralığında olmalıdır.")
        secilen = []
        sonraki_izinli = 0
        for index, (probability, market_return) in enumerate(zip(probabilities, future_returns)):
            if index < sonraki_izinli or float(probability) < threshold:
                continue
            net_return = float(market_return)
            if not returns_are_net:
                net_return -= self.round_trip_cost_rate
            secilen.append(net_return)
            sonraki_izinli = index + self.horizon_bars

        gross_profit = sum(value for value in secilen if value > 0)
        gross_loss = sum(value for value in secilen if value < 0)
        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for value in secilen:
            equity += value
            peak = max(peak, equity)
            max_drawdown = min(max_drawdown, equity - peak)
        return {
            'signal_count': len(secilen),
            'wins': sum(value > 0 for value in secilen),
            'win_rate': (sum(value > 0 for value in secilen) / len(secilen)) if secilen else 0.0,
            'net_return': sum(secilen),
            'profit_factor': (gross_profit / abs(gross_loss)) if gross_loss < 0 else (float('inf') if gross_profit > 0 else 0.0),
            'max_drawdown': abs(max_drawdown),
        }

    @staticmethod
    def _sinif_agirligi(targets):
        sayilar = np.bincount(np.asarray(targets, dtype=int), minlength=2)
        return float(sayilar[0] / max(sayilar[1], 1))

    @staticmethod
    def _dengeli_dogruluk(targets, predictions):
        y_true = np.asarray(targets, dtype=int)
        y_pred = np.asarray(predictions, dtype=int)
        if len(y_true) == 0 or len(y_true) != len(y_pred):
            raise ValueError("Dengeli doğruluk girdileri boş veya uyumsuz.")
        recalls = []
        for sinif in np.unique(y_true):
            mask = y_true == sinif
            recalls.append(float(np.mean(y_pred[mask] == sinif)))
        return float(np.mean(recalls))

    @staticmethod
    def _brier_skoru(targets, probabilities):
        y_true = np.asarray(targets, dtype=float)
        probability = np.asarray(probabilities, dtype=float)
        if len(y_true) == 0 or len(y_true) != len(probability):
            raise ValueError("Brier girdileri boş veya uyumsuz.")
        if not np.isfinite(probability).all():
            raise ValueError("Brier olasılıkları sonlu olmalıdır.")
        return float(np.mean((probability - y_true) ** 2))

    def _olasilik_diagnostik_ozeti(self, probabilities):
        values = np.asarray(probabilities, dtype=float)
        if len(values) == 0 or not np.isfinite(values).all():
            raise ValueError("Olasılık diagnostik girdisi boş veya sonlu değil.")
        quantiles = np.quantile(values, [0.10, 0.25, 0.50, 0.75, 0.90])
        return {
            "count": int(len(values)),
            "min": round(float(np.min(values)), 6),
            "p10": round(float(quantiles[0]), 6),
            "p25": round(float(quantiles[1]), 6),
            "median": round(float(quantiles[2]), 6),
            "p75": round(float(quantiles[3]), 6),
            "p90": round(float(quantiles[4]), 6),
            "max": round(float(np.max(values)), 6),
            "mean": round(float(np.mean(values)), 6),
            "std": round(float(np.std(values)), 6),
            "above_classification_threshold": int(np.sum(values >= 0.50)),
            "above_signal_threshold": int(
                np.sum(values >= self.signal_threshold)
            ),
        }

    def _v6_esik_arastirmasi(
        self,
        *,
        cv_probabilities,
        cv_targets,
        cv_net_returns,
        holdout_probabilities,
        holdout_targets,
        holdout_net_returns,
    ):
        if self.label_schema_version != 6:
            raise RuntimeError("V6 eşik araştırması yalnızca schema 6 içindir.")

        cv_probability = np.asarray(cv_probabilities, dtype=float)
        cv_target = np.asarray(cv_targets, dtype=int)
        cv_returns = np.asarray(cv_net_returns, dtype=float)
        holdout_probability = np.asarray(holdout_probabilities, dtype=float)
        holdout_target = np.asarray(holdout_targets, dtype=int)
        holdout_returns = np.asarray(holdout_net_returns, dtype=float)
        for name, values, expected in (
            ("cv_targets", cv_target, len(cv_probability)),
            ("cv_net_returns", cv_returns, len(cv_probability)),
            ("holdout_targets", holdout_target, len(holdout_probability)),
            ("holdout_net_returns", holdout_returns, len(holdout_probability)),
        ):
            if len(values) != expected:
                raise ValueError(f"V6 eşik araştırması {name} boyutu uyumsuz.")
        if (
            not np.isfinite(cv_probability).all()
            or not np.isfinite(cv_returns).all()
            or not np.isfinite(holdout_probability).all()
            or not np.isfinite(holdout_returns).all()
        ):
            raise ValueError("V6 eşik araştırması sonlu girdiler gerektirir.")

        classification_rows = []
        for threshold in np.round(np.arange(0.10, 0.501, 0.01), 2):
            score = self._dengeli_dogruluk(
                cv_target,
                cv_probability >= threshold,
            )
            classification_rows.append(
                {
                    "threshold": float(threshold),
                    "cv_balanced_accuracy": round(float(score), 6),
                }
            )
        selected_classification = max(
            classification_rows,
            key=lambda row: (
                row["cv_balanced_accuracy"],
                row["threshold"],
            ),
        )
        classification_threshold = float(
            selected_classification["threshold"]
        )
        holdout_balanced_accuracy = self._dengeli_dogruluk(
            holdout_target,
            holdout_probability >= classification_threshold,
        )

        def strategy_payload(metrics):
            profit_factor = float(metrics["profit_factor"])
            return {
                "signal_count": int(metrics["signal_count"]),
                "wins": int(metrics["wins"]),
                "win_rate": round(float(metrics["win_rate"]), 6),
                "net_return": round(float(metrics["net_return"]), 8),
                "profit_factor": (
                    round(profit_factor, 6)
                    if math.isfinite(profit_factor)
                    else 999.0
                ),
                "max_drawdown": round(
                    float(metrics["max_drawdown"]),
                    8,
                ),
            }

        minimum_cv_signals = max(20, int(math.ceil(len(cv_probability) * 0.01)))
        signal_rows = []
        for threshold in np.round(np.arange(0.10, 0.601, 0.01), 2):
            metrics = self._strateji_metrikleri(
                cv_probability,
                cv_returns,
                returns_are_net=True,
                signal_threshold=threshold,
            )
            signal_rows.append(
                {
                    "threshold": float(threshold),
                    **strategy_payload(metrics),
                }
            )
        eligible_signal_rows = [
            row
            for row in signal_rows
            if row["signal_count"] >= minimum_cv_signals
        ]
        selected_signal = max(
            eligible_signal_rows or signal_rows,
            key=lambda row: (
                row["net_return"],
                row["profit_factor"],
                row["win_rate"],
                row["threshold"],
            ),
        )
        signal_threshold = float(selected_signal["threshold"])
        holdout_strategy = self._strateji_metrikleri(
            holdout_probability,
            holdout_returns,
            returns_are_net=True,
            signal_threshold=signal_threshold,
        )

        return {
            "schema_version": 1,
            "selection_scope": "cv_oof_only",
            "holdout_used_for_selection": False,
            "activated": False,
            "classification": {
                "selected_threshold": classification_threshold,
                "cv_balanced_accuracy": selected_classification[
                    "cv_balanced_accuracy"
                ],
                "holdout_balanced_accuracy": round(
                    float(holdout_balanced_accuracy),
                    6,
                ),
                "candidates": classification_rows,
            },
            "signal": {
                "selected_threshold": signal_threshold,
                "minimum_cv_signal_count": minimum_cv_signals,
                "cv_strategy": {
                    key: value
                    for key, value in selected_signal.items()
                    if key != "threshold"
                },
                "holdout_strategy": strategy_payload(holdout_strategy),
                "candidates": signal_rows,
            },
        }

    def _v6_permutasyon_katkisi(
        self,
        *,
        model,
        features,
        targets,
        feature_names,
        baseline_balanced_accuracy,
        baseline_brier,
        seed,
    ):
        matrix = np.asarray(features, dtype=float)
        y_true = np.asarray(targets, dtype=int)
        if matrix.ndim != 2 or matrix.shape[0] != len(y_true):
            raise ValueError("V6 permutation feature matrisi uyumsuz.")
        if matrix.shape[1] != len(feature_names):
            raise ValueError("V6 permutation feature adları matrise uymuyor.")
        rng = np.random.default_rng(int(seed))
        rows = []
        for feature_index, feature_name in enumerate(feature_names):
            permuted = matrix.copy()
            order = rng.permutation(len(permuted))
            permuted[:, feature_index] = permuted[order, feature_index]
            probability = self._pozitif_sinif_olasiligi(model, permuted)
            permuted_accuracy = self._dengeli_dogruluk(
                y_true,
                probability >= 0.5,
            )
            permuted_brier = self._brier_skoru(y_true, probability)
            rows.append(
                {
                    "feature": str(feature_name),
                    "balanced_accuracy_drop": round(
                        float(baseline_balanced_accuracy - permuted_accuracy),
                        8,
                    ),
                    "brier_increase": round(
                        float(permuted_brier - baseline_brier),
                        8,
                    ),
                }
            )
        return rows

    @staticmethod
    def _v6_permutasyon_katkisi_birlestir(fold_rows):
        grouped = {}
        for fold_number, rows in enumerate(fold_rows, start=1):
            for row in rows:
                grouped.setdefault(row["feature"], []).append(
                    {
                        "fold": fold_number,
                        "balanced_accuracy_drop": float(
                            row["balanced_accuracy_drop"]
                        ),
                        "brier_increase": float(row["brier_increase"]),
                    }
                )
        result = []
        for feature_name, contributions in grouped.items():
            accuracy_drops = np.asarray(
                [
                    row["balanced_accuracy_drop"]
                    for row in contributions
                ],
                dtype=float,
            )
            brier_increases = np.asarray(
                [row["brier_increase"] for row in contributions],
                dtype=float,
            )
            result.append(
                {
                    "feature": feature_name,
                    "mean_balanced_accuracy_drop": round(
                        float(np.mean(accuracy_drops)),
                        8,
                    ),
                    "mean_brier_increase": round(
                        float(np.mean(brier_increases)),
                        8,
                    ),
                    "positive_accuracy_folds": int(
                        np.sum(accuracy_drops > 0.0)
                    ),
                    "positive_brier_folds": int(
                        np.sum(brier_increases > 0.0)
                    ),
                    "folds": contributions,
                }
            )
        result.sort(
            key=lambda row: (
                row["mean_brier_increase"],
                row["mean_balanced_accuracy_drop"],
                row["feature"],
            ),
            reverse=True,
        )
        return result

    @staticmethod
    def _v6_shadow_featureleri_sec(feature_contribution):
        selected = [
            row["feature"]
            for row in feature_contribution
            if float(row["mean_brier_increase"]) > 0.0
            and int(row["positive_brier_folds"]) >= 2
            and int(row["positive_accuracy_folds"]) >= 2
        ]
        return selected[:12]

    def _v6_azaltilmis_feature_shadow_degerlendir(
        self,
        *,
        algoritma,
        feature_ready,
        cv_folds,
        holdout,
        selected_features,
    ):
        selection_rule = {
            "mean_brier_increase_gt": 0.0,
            "min_positive_brier_folds": 2,
            "min_positive_accuracy_folds": 2,
            "min_selected_features": 3,
            "max_selected_features": 12,
        }
        report = {
            "schema_version": 1,
            "selection_scope": "baseline_cv_permutation_only",
            "holdout_used_for_selection": False,
            "holdout_role": "research_comparison_not_promotion_evidence",
            "activated": False,
            "artifact_saved": False,
            "selection_rule": selection_rule,
            "selected_features": list(selected_features),
        }
        if len(selected_features) < selection_rule["min_selected_features"]:
            report.update(
                {
                    "status": "skipped",
                    "reason": (
                        "selected_feature_count="
                        f"{len(selected_features)}"
                        f"<{selection_rule['min_selected_features']}"
                    ),
                }
            )
            return report

        cv_probabilities = []
        cv_targets = []
        cv_net_returns = []
        fold_rows = []
        for fold_number, fold in enumerate(cv_folds, start=1):
            train_frame = feature_ready.loc[fold.train_index]
            validation_frame = feature_ready.loc[fold.validation_index]
            y_train = train_frame["Hedef_Yön"].to_numpy(dtype=int)
            y_validation = validation_frame["Hedef_Yön"].to_numpy(dtype=int)
            model = self._siniflandirici_olustur(
                algoritma,
                y_train,
                n_estimators=100,
            )
            model.fit(
                train_frame[selected_features].to_numpy(),
                y_train,
            )
            probability = self._pozitif_sinif_olasiligi(
                model,
                validation_frame[selected_features].to_numpy(),
            )
            cv_probabilities.extend(probability.tolist())
            cv_targets.extend(y_validation.tolist())
            cv_net_returns.extend(
                validation_frame["Gelecek_Net_Ret"].to_numpy(
                    dtype=float
                ).tolist()
            )
            fold_rows.append(
                {
                    "fold": fold_number,
                    "train_rows": int(len(train_frame)),
                    "validation_rows": int(len(validation_frame)),
                    "raw_balanced_accuracy": round(
                        float(
                            self._dengeli_dogruluk(
                                y_validation,
                                probability >= 0.5,
                            )
                        ),
                        6,
                    ),
                    "raw_brier_score": round(
                        float(
                            self._brier_skoru(
                                y_validation,
                                probability,
                            )
                        ),
                        6,
                    ),
                }
            )

        calibration_a, calibration_b = self._platt_kalibrasyon_uydur(
            cv_probabilities,
            cv_targets,
        )
        cv_calibrated = self._kalibrasyon_uygula(
            cv_probabilities,
            calibration_a,
            calibration_b,
        )
        cv_balanced_accuracy = self._dengeli_dogruluk(
            cv_targets,
            cv_calibrated >= 0.5,
        )
        cv_brier = self._brier_skoru(cv_targets, cv_calibrated)

        holdout_train = feature_ready.loc[holdout.train_index]
        holdout_frame = feature_ready.loc[holdout.validation_index]
        y_holdout_train = holdout_train["Hedef_Yön"].to_numpy(dtype=int)
        holdout_targets = holdout_frame["Hedef_Yön"].to_numpy(dtype=int)
        holdout_net_returns = holdout_frame["Gelecek_Net_Ret"].to_numpy(
            dtype=float
        )
        holdout_model = self._siniflandirici_olustur(
            algoritma,
            y_holdout_train,
            n_estimators=self.n_estimators,
        )
        holdout_model.fit(
            holdout_train[selected_features].to_numpy(),
            y_holdout_train,
        )
        holdout_raw = self._pozitif_sinif_olasiligi(
            holdout_model,
            holdout_frame[selected_features].to_numpy(),
        )
        holdout_calibrated = self._kalibrasyon_uygula(
            holdout_raw,
            calibration_a,
            calibration_b,
        )
        holdout_balanced_accuracy = self._dengeli_dogruluk(
            holdout_targets,
            holdout_calibrated >= 0.5,
        )
        holdout_brier = self._brier_skoru(
            holdout_targets,
            holdout_calibrated,
        )
        default_strategy = self._strateji_metrikleri(
            holdout_calibrated,
            holdout_net_returns,
            returns_are_net=True,
        )
        threshold_research = self._v6_esik_arastirmasi(
            cv_probabilities=cv_calibrated,
            cv_targets=cv_targets,
            cv_net_returns=cv_net_returns,
            holdout_probabilities=holdout_calibrated,
            holdout_targets=holdout_targets,
            holdout_net_returns=holdout_net_returns,
        )

        def strategy_payload(metrics):
            profit_factor = float(metrics["profit_factor"])
            return {
                "signal_count": int(metrics["signal_count"]),
                "win_rate": round(float(metrics["win_rate"]), 6),
                "net_return": round(float(metrics["net_return"]), 8),
                "profit_factor": (
                    round(profit_factor, 6)
                    if math.isfinite(profit_factor)
                    else 999.0
                ),
                "max_drawdown": round(
                    float(metrics["max_drawdown"]),
                    8,
                ),
            }

        report.update(
            {
                "status": "evaluated",
                "fold_rows": fold_rows,
                "calibration": {
                    "method": "platt_logit",
                    "a": round(float(calibration_a), 8),
                    "b": round(float(calibration_b), 8),
                },
                "cv": {
                    "oof_rows": int(len(cv_targets)),
                    "calibrated_balanced_accuracy": round(
                        float(cv_balanced_accuracy),
                        6,
                    ),
                    "calibrated_brier_score": round(
                        float(cv_brier),
                        6,
                    ),
                },
                "holdout": {
                    "rows": int(len(holdout_targets)),
                    "calibrated_balanced_accuracy": round(
                        float(holdout_balanced_accuracy),
                        6,
                    ),
                    "calibrated_brier_score": round(
                        float(holdout_brier),
                        6,
                    ),
                    "default_strategy": strategy_payload(
                        default_strategy
                    ),
                },
                "threshold_research": threshold_research,
            }
        )
        return report

    def _v6_artifact_kalite_kapisi(
        self,
        *,
        cv_targets,
        cv_balanced_accuracy,
        cv_brier,
        recent_targets,
        recent_balanced_accuracy,
        recent_brier,
        recent_strategy,
    ):
        if self.label_schema_version != 6:
            raise RuntimeError("V6 artifact kalite kapısı yalnızca schema 6 içindir.")

        thresholds = dict(self.v6_artifact_quality_thresholds)

        def brier_skill(targets, score):
            values = np.asarray(targets, dtype=float)
            prevalence = float(np.mean(values))
            baseline = prevalence * (1.0 - prevalence)
            if baseline <= 0.0:
                return None, baseline
            return 1.0 - (float(score) / baseline), baseline

        cv_skill, cv_baseline = brier_skill(cv_targets, cv_brier)
        recent_skill, recent_baseline = brier_skill(
            recent_targets,
            recent_brier,
        )
        signal_count = int(recent_strategy["signal_count"])
        net_return = float(recent_strategy["net_return"])
        profit_factor = float(recent_strategy["profit_factor"])

        reasons = []
        minimum_accuracy = thresholds["min_balanced_accuracy"]
        if float(cv_balanced_accuracy) < minimum_accuracy:
            reasons.append(
                f"cv_balanced_accuracy={float(cv_balanced_accuracy):.4f}"
                f"<{minimum_accuracy:.4f}"
            )
        if float(recent_balanced_accuracy) < minimum_accuracy:
            reasons.append(
                f"recent_balanced_accuracy="
                f"{float(recent_balanced_accuracy):.4f}"
                f"<{minimum_accuracy:.4f}"
            )

        maximum_brier = thresholds["max_brier_score"]
        if float(cv_brier) > maximum_brier:
            reasons.append(f"cv_brier={float(cv_brier):.4f}>{maximum_brier:.4f}")
        if float(recent_brier) > maximum_brier:
            reasons.append(
                f"recent_brier={float(recent_brier):.4f}>{maximum_brier:.4f}"
            )

        minimum_skill = thresholds["min_brier_skill"]
        if cv_skill is None:
            reasons.append("cv_brier_baseline_missing")
        elif cv_skill < minimum_skill:
            reasons.append(f"cv_brier_skill={cv_skill:.4f}<{minimum_skill:.4f}")
        if recent_skill is None:
            reasons.append("recent_brier_baseline_missing")
        elif recent_skill < minimum_skill:
            reasons.append(
                f"recent_brier_skill={recent_skill:.4f}<{minimum_skill:.4f}"
            )

        minimum_signals = int(thresholds["min_recent_signal_count"])
        if signal_count < minimum_signals:
            reasons.append(f"recent_signal_count={signal_count}<{minimum_signals}")
        minimum_net = float(thresholds["min_recent_net_return"])
        if net_return <= minimum_net:
            reasons.append(
                f"recent_net_return={net_return:.8f}<={minimum_net:.8f}"
            )
        minimum_pf = float(thresholds["min_recent_profit_factor"])
        if profit_factor < minimum_pf:
            reasons.append(
                f"recent_profit_factor={profit_factor:.4f}<{minimum_pf:.4f}"
            )

        return {
            "passed": not reasons,
            "reasons": reasons,
            "thresholds": thresholds,
            "metrics": {
                "cv_balanced_accuracy": round(
                    float(cv_balanced_accuracy),
                    6,
                ),
                "cv_brier_score": round(float(cv_brier), 6),
                "cv_brier_baseline": round(float(cv_baseline), 6),
                "cv_brier_skill": (
                    round(float(cv_skill), 6) if cv_skill is not None else None
                ),
                "recent_balanced_accuracy": round(
                    float(recent_balanced_accuracy),
                    6,
                ),
                "recent_brier_score": round(float(recent_brier), 6),
                "recent_brier_baseline": round(float(recent_baseline), 6),
                "recent_brier_skill": (
                    round(float(recent_skill), 6)
                    if recent_skill is not None
                    else None
                ),
                "recent_signal_count": signal_count,
                "recent_strategy_net_return": round(net_return, 8),
                "recent_strategy_profit_factor": (
                    round(profit_factor, 6)
                    if math.isfinite(profit_factor)
                    else 999.0
                ),
            },
        }

    @staticmethod
    def _pozitif_sinif_olasiligi(model, features):
        probabilities = np.asarray(model.predict_proba(features), dtype=float)
        if (
            probabilities.ndim != 2
            or probabilities.shape[0] != len(features)
            or probabilities.shape[1] < 2
        ):
            raise ValueError("Model predict_proba çıktısı ikili sınıfa uygun değil.")
        positive = probabilities[:, 1]
        if (
            not np.isfinite(positive).all()
            or np.any(positive < 0.0)
            or np.any(positive > 1.0)
        ):
            raise ValueError("Model geçersiz pozitif sınıf olasılığı üretti.")
        return positive

    def _platt_kalibrasyon_uydur(self, probabilities, targets):
        probability = np.asarray(probabilities, dtype=float)
        y_true = np.asarray(targets, dtype=int)
        if len(probability) < 50 or len(np.unique(y_true)) != 2:
            raise ValueError(
                "V6 kalibrasyonu için en az 50 OOF tahmin ve iki sınıf gerekli."
            )
        from sklearn.linear_model import LogisticRegression

        calibrator = LogisticRegression(
            C=1.0,
            solver="lbfgs",
            random_state=self.random_state,
        )
        calibrator.fit(self._logit(probability).reshape(-1, 1), y_true)
        return (
            float(calibrator.coef_[0][0]),
            float(calibrator.intercept_[0]),
        )

    def _siniflandirici_olustur(self, algoritma, targets, *, n_estimators):
        scale_pos_weight = self._sinif_agirligi(targets)
        if algoritma == "lightgbm":
            import lightgbm as lgb

            return lgb.LGBMClassifier(
                n_estimators=int(n_estimators),
                max_depth=self.max_depth,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                scale_pos_weight=scale_pos_weight,
                random_state=self.random_state,
                force_col_wise=True,
                verbose=-1,
            )
        if algoritma == "xgboost":
            import xgboost as xgb

            return xgb.XGBClassifier(
                n_estimators=int(n_estimators),
                max_depth=self.max_depth,
                learning_rate=0.03,
                subsample=0.7,
                colsample_bytree=0.7,
                min_child_weight=5,
                reg_alpha=0.1,
                reg_lambda=1.0,
                gamma=0.1,
                scale_pos_weight=scale_pos_weight,
                random_state=self.random_state,
                eval_metric="logloss",
            )
        raise ValueError(f"Desteklenmeyen algoritma: {algoritma!r}")

    def _v6_feature_provenance_dogrula(self, df, *, is_crypto):
        try:
            feature_schema_version = int(
                df.attrs.get("feature_schema_version")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "V6 eğitim için feature_schema_version=6 provenance gerekli."
            ) from exc
        if feature_schema_version != 6:
            raise ValueError(
                "V6 eğitim yalnızca feature_schema_version=6 veri kabul eder."
            )
        df_timeframe = str(df.attrs.get("base_timeframe") or self.base_timeframe)
        if df_timeframe != self.base_timeframe:
            raise ValueError(
                f"V6 eğitim base_timeframe={self.base_timeframe} bekliyor ancak gelen veri {df_timeframe}."
            )
        feature_contract_id = str(df.attrs.get("feature_contract_id") or "")
        if feature_contract_id != self.feature_availability_spec.contract_id:
            raise ValueError("V6 feature sözleşme kimliği eksik veya uyumsuz.")
        provenance = {
            "feature_schema_version": feature_schema_version,
            "base_timeframe": self.base_timeframe,
            "feature_contract_id": feature_contract_id,
        }
        if is_crypto:
            coverage_contract_id = str(
                df.attrs.get("coverage_contract_id") or ""
            )
            if coverage_contract_id != self.feature_coverage_spec.contract_id:
                raise ValueError(
                    "V6 coverage sözleşme kimliği eksik veya uyumsuz."
                )
            feature_quality = df.attrs.get("feature_quality")
            if not isinstance(feature_quality, dict):
                raise ValueError("V6 feature_quality provenance gerekli.")
            for feature_name in ("Open_Interest", "Funding_Rate"):
                report = feature_quality.get(feature_name)
                self.feature_coverage_spec.validate_frame_report(
                    df,
                    feature_name=feature_name,
                    report=report,
                )
            provenance.update(
                {
                    "coverage_contract_id": coverage_contract_id,
                    "feature_quality": feature_quality,
                }
            )
        return provenance

    def _v6_model_egit(self, sembol, df, is_crypto=True, algoritma="xgboost"):
        import time

        baslama_zamani = time.time()
        provenance = self._v6_feature_provenance_dogrula(
            df,
            is_crypto=is_crypto,
        )
        training_frame = df
        joint_rows = None
        if is_crypto:
            missing_masks = [
                column
                for column in (
                    "Open_Interest_Available",
                    "Funding_Rate_Available",
                )
                if column not in df.columns
            ]
            if missing_masks:
                raise ValueError(f"V6 coverage maskeleri eksik: {missing_masks}")
            joint_available = (
                pd.to_numeric(
                    df["Open_Interest_Available"],
                    errors="coerce",
                ).fillna(0).astype(bool)
                & pd.to_numeric(
                    df["Funding_Rate_Available"],
                    errors="coerce",
                ).fillna(0).astype(bool)
            )
            joint_values = joint_available.to_numpy(dtype=bool)
            if not bool(joint_values[-1]):
                raise ValueError(
                    "V6 ortak OI/funding kapsamı son mumda kullanılamıyor."
                )
            unavailable_positions = np.flatnonzero(~joint_values)
            suffix_start = (
                int(unavailable_positions[-1]) + 1
                if len(unavailable_positions)
                else 0
            )
            training_frame = df.iloc[suffix_start:].copy()
            joint_rows = int(len(training_frame))
            if joint_rows < self.feature_coverage_spec.min_joint_available_bars:
                raise ValueError(
                    "V6 kesintisiz ortak OI/funding kapsamı yetersiz: "
                    f"{joint_rows}<"
                    f"{self.feature_coverage_spec.min_joint_available_bars}"
                )
            self.training_split_spec.validate_index(training_frame.index)

        plan = self.v6_egitim_plani_hazirla(training_frame)
        aktif_features = self.crypto_features if is_crypto else self.stock_features

        prepared = self.df_hazirla(
            training_frame.copy(),
            drop_neutral=False,
        )
        feature_ready = self._featureleri_dogrula(
            prepared,
            aktif_features,
            hedef_gerekli=True,
        )
        if len(feature_ready) < 350:
            raise ValueError(
                f"V6 eğitim için veri yetersiz: {len(feature_ready)} mum (min 350)"
            )

        planned_cv_folds = plan["planned_cv_folds"]
        cv_folds = tuple(
            fold.select_eligible(feature_ready.index)
            for fold in planned_cv_folds
        )
        planned_holdout = plan["planned_holdout"]
        holdout = planned_holdout.select_eligible(feature_ready.index)
        if len(holdout.validation_index) != plan["holdout_observations"]:
            raise ValueError(
                "V6 feature-ready holdout kapsamı eksik: "
                f"{len(holdout.validation_index)}/"
                f"{plan['holdout_observations']}"
            )

        cv_probabilities = []
        cv_targets = []
        cv_net_returns = []
        cv_scores = []
        cv_fold_rows = []
        cv_feature_contribution_rows = []
        for fold_number, fold in enumerate(cv_folds, start=1):
            train_frame = feature_ready.loc[fold.train_index]
            validation_frame = feature_ready.loc[fold.validation_index]
            if len(train_frame) < self.training_split_spec.min_train_bars:
                raise ValueError(f"V6 CV fold {fold_number} eğitim verisi yetersiz.")
            if (
                len(validation_frame)
                < self.training_split_spec.min_validation_bars
            ):
                raise ValueError(
                    f"V6 CV fold {fold_number} doğrulama verisi yetersiz."
                )

            y_train = train_frame["Hedef_Yön"].to_numpy(dtype=int)
            y_validation = validation_frame["Hedef_Yön"].to_numpy(dtype=int)
            if len(np.unique(y_train)) != 2:
                raise ValueError(f"V6 CV fold {fold_number} eğitim hedefi tek sınıf.")

            cv_model = self._siniflandirici_olustur(
                algoritma,
                y_train,
                n_estimators=100,
            )
            cv_model.fit(
                train_frame[aktif_features].to_numpy(),
                y_train,
            )
            fold_probability = self._pozitif_sinif_olasiligi(
                cv_model,
                validation_frame[aktif_features].to_numpy(),
            )
            fold_balanced_accuracy = self._dengeli_dogruluk(
                y_validation,
                fold_probability >= 0.5,
            )
            fold_brier = self._brier_skoru(
                y_validation,
                fold_probability,
            )
            fold_feature_contributions = self._v6_permutasyon_katkisi(
                model=cv_model,
                features=validation_frame[aktif_features].to_numpy(),
                targets=y_validation,
                feature_names=aktif_features,
                baseline_balanced_accuracy=fold_balanced_accuracy,
                baseline_brier=fold_brier,
                seed=self.random_state + fold_number,
            )
            cv_feature_contribution_rows.append(
                fold_feature_contributions
            )
            cv_probabilities.extend(fold_probability.tolist())
            cv_targets.extend(y_validation.tolist())
            cv_net_returns.extend(
                validation_frame["Gelecek_Net_Ret"].to_numpy(
                    dtype=float
                ).tolist()
            )
            cv_scores.append(fold_balanced_accuracy)
            cv_fold_rows.append(
                {
                    "fold": fold_number,
                    "train_rows": int(len(train_frame)),
                    "purge_rows": int(len(fold.purge_index)),
                    "validation_rows": int(len(validation_frame)),
                    "embargo_rows": int(len(fold.embargo_index)),
                    "train_start": train_frame.index[0].isoformat(),
                    "train_end": train_frame.index[-1].isoformat(),
                    "validation_start": validation_frame.index[0].isoformat(),
                    "validation_end": validation_frame.index[-1].isoformat(),
                    "validation_positive_prevalence": round(
                        float(np.mean(y_validation)),
                        6,
                    ),
                    "raw_balanced_accuracy": round(
                        float(fold_balanced_accuracy),
                        6,
                    ),
                    "raw_brier_score": round(float(fold_brier), 6),
                    "raw_probability_summary": (
                        self._olasilik_diagnostik_ozeti(fold_probability)
                    ),
                }
            )

        cv_raw_balanced_accuracy = self._dengeli_dogruluk(
            cv_targets,
            np.asarray(cv_probabilities) >= 0.5,
        )
        cv_raw_brier = self._brier_skoru(
            cv_targets,
            cv_probabilities,
        )
        feature_contribution = self._v6_permutasyon_katkisi_birlestir(
            cv_feature_contribution_rows
        )
        calibration_a, calibration_b = self._platt_kalibrasyon_uydur(
            cv_probabilities,
            cv_targets,
        )
        cv_calibrated = self._kalibrasyon_uygula(
            cv_probabilities,
            calibration_a,
            calibration_b,
        )
        cv_balanced_accuracy = self._dengeli_dogruluk(
            cv_targets,
            cv_calibrated >= 0.5,
        )
        cv_brier = self._brier_skoru(cv_targets, cv_calibrated)

        holdout_train = feature_ready.loc[holdout.train_index]
        holdout_frame = feature_ready.loc[holdout.validation_index]
        y_holdout_train = holdout_train["Hedef_Yön"].to_numpy(dtype=int)
        holdout_actual = holdout_frame["Hedef_Yön"].to_numpy(dtype=int)
        if len(np.unique(y_holdout_train)) != 2:
            raise ValueError("V6 holdout eğitim hedefi tek sınıfa düştü.")
        if len(np.unique(holdout_actual)) != 2:
            raise ValueError("V6 holdout değerlendirmesi iki sınıf içermiyor.")

        holdout_model = self._siniflandirici_olustur(
            algoritma,
            y_holdout_train,
            n_estimators=self.n_estimators,
        )
        holdout_model.fit(
            holdout_train[aktif_features].to_numpy(),
            y_holdout_train,
        )
        holdout_raw = self._pozitif_sinif_olasiligi(
            holdout_model,
            holdout_frame[aktif_features].to_numpy(),
        )
        holdout_probability = self._kalibrasyon_uygula(
            holdout_raw,
            calibration_a,
            calibration_b,
        )
        holdout_raw_balanced_accuracy = self._dengeli_dogruluk(
            holdout_actual,
            holdout_raw >= 0.5,
        )
        holdout_raw_brier = self._brier_skoru(
            holdout_actual,
            holdout_raw,
        )
        recent_balanced_accuracy = self._dengeli_dogruluk(
            holdout_actual,
            holdout_probability >= 0.5,
        )
        recent_brier = self._brier_skoru(
            holdout_actual,
            holdout_probability,
        )
        holdout_net_returns = holdout_frame["Gelecek_Net_Ret"].to_numpy(
            dtype=float
        )
        recent_strategy = self._strateji_metrikleri(
            holdout_probability,
            holdout_net_returns,
            returns_are_net=True,
        )
        holdout_raw_strategy = self._strateji_metrikleri(
            holdout_raw,
            holdout_net_returns,
            returns_are_net=True,
        )
        threshold_research = self._v6_esik_arastirmasi(
            cv_probabilities=cv_calibrated,
            cv_targets=cv_targets,
            cv_net_returns=cv_net_returns,
            holdout_probabilities=holdout_probability,
            holdout_targets=holdout_actual,
            holdout_net_returns=holdout_net_returns,
        )
        selected_shadow_features = self._v6_shadow_featureleri_sec(
            feature_contribution
        )
        feature_subset_shadow = (
            self._v6_azaltilmis_feature_shadow_degerlendir(
                algoritma=algoritma,
                feature_ready=feature_ready,
                cv_folds=cv_folds,
                holdout=holdout,
                selected_features=selected_shadow_features,
            )
        )
        if feature_subset_shadow["status"] == "evaluated":
            feature_subset_shadow["comparison_to_full_model"] = {
                "cv_balanced_accuracy_delta": round(
                    float(
                        feature_subset_shadow["cv"][
                            "calibrated_balanced_accuracy"
                        ]
                        - cv_balanced_accuracy
                    ),
                    6,
                ),
                "cv_brier_improvement": round(
                    float(
                        cv_brier
                        - feature_subset_shadow["cv"][
                            "calibrated_brier_score"
                        ]
                    ),
                    6,
                ),
                "holdout_balanced_accuracy_delta": round(
                    float(
                        feature_subset_shadow["holdout"][
                            "calibrated_balanced_accuracy"
                        ]
                        - recent_balanced_accuracy
                    ),
                    6,
                ),
                "holdout_brier_improvement": round(
                    float(
                        recent_brier
                        - feature_subset_shadow["holdout"][
                            "calibrated_brier_score"
                        ]
                    ),
                    6,
                ),
            }
        kalite_skoru = min(cv_balanced_accuracy, recent_balanced_accuracy)

        final_targets = feature_ready["Hedef_Yön"].to_numpy(dtype=int)
        if len(np.unique(final_targets)) != 2:
            raise ValueError("V6 nihai eğitim hedefi tek sınıfa düştü.")

        safe_name = sembol.replace("/", "-")
        base_prefix = self.model_prefix if is_crypto else "v6_stock_beyin"
        prefix = (
            "lgbm_" + base_prefix
            if algoritma == "lightgbm"
            else base_prefix
        )
        model_file = f"{prefix}_{safe_name}.pkl"
        meta_file = f"{prefix}_{safe_name}_meta.json"
        sinif_sayilari = np.bincount(final_targets, minlength=2)
        gross_holdout_returns = holdout_frame["Gelecek_Ret"].to_numpy(dtype=float)
        artifact_quality_gate = self._v6_artifact_kalite_kapisi(
            cv_targets=cv_targets,
            cv_balanced_accuracy=cv_balanced_accuracy,
            cv_brier=cv_brier,
            recent_targets=holdout_actual,
            recent_balanced_accuracy=recent_balanced_accuracy,
            recent_brier=recent_brier,
            recent_strategy=recent_strategy,
        )
        prediction_diagnostics = {
            "schema_version": 1,
            "threshold_research": threshold_research,
            "feature_contribution": {
                "method": "validation_permutation_raw_probability",
                "selection_scope": "cv_validation_only",
                "activated": False,
                "ranking": feature_contribution,
            },
            "feature_subset_shadow": feature_subset_shadow,
            "cv": {
                "target_positive_prevalence": round(
                    float(np.mean(cv_targets)),
                    6,
                ),
                "raw_balanced_accuracy": round(
                    float(cv_raw_balanced_accuracy),
                    6,
                ),
                "raw_brier_score": round(float(cv_raw_brier), 6),
                "raw_probability_summary": (
                    self._olasilik_diagnostik_ozeti(cv_probabilities)
                ),
                "calibrated_balanced_accuracy": round(
                    float(cv_balanced_accuracy),
                    6,
                ),
                "calibrated_brier_score": round(float(cv_brier), 6),
                "calibrated_probability_summary": (
                    self._olasilik_diagnostik_ozeti(cv_calibrated)
                ),
            },
            "holdout": {
                "target_positive_prevalence": round(
                    float(np.mean(holdout_actual)),
                    6,
                ),
                "raw_balanced_accuracy": round(
                    float(holdout_raw_balanced_accuracy),
                    6,
                ),
                "raw_brier_score": round(float(holdout_raw_brier), 6),
                "raw_probability_summary": (
                    self._olasilik_diagnostik_ozeti(holdout_raw)
                ),
                "raw_strategy": {
                    "signal_count": int(
                        holdout_raw_strategy["signal_count"]
                    ),
                    "net_return": round(
                        float(holdout_raw_strategy["net_return"]),
                        8,
                    ),
                    "profit_factor": (
                        round(
                            float(holdout_raw_strategy["profit_factor"]),
                            6,
                        )
                        if math.isfinite(
                            float(holdout_raw_strategy["profit_factor"])
                        )
                        else 999.0
                    ),
                },
                "calibrated_balanced_accuracy": round(
                    float(recent_balanced_accuracy),
                    6,
                ),
                "calibrated_brier_score": round(float(recent_brier), 6),
                "calibrated_probability_summary": (
                    self._olasilik_diagnostik_ozeti(holdout_probability)
                ),
                "calibrated_strategy": {
                    "signal_count": int(recent_strategy["signal_count"]),
                    "net_return": round(
                        float(recent_strategy["net_return"]),
                        8,
                    ),
                    "profit_factor": (
                        round(
                            float(recent_strategy["profit_factor"]),
                            6,
                        )
                        if math.isfinite(
                            float(recent_strategy["profit_factor"])
                        )
                        else 999.0
                    ),
                },
            },
            "calibration": {
                "method": "platt_logit",
                "a": round(float(calibration_a), 8),
                "b": round(float(calibration_b), 8),
            },
        }

        meta = {
            "egitim_zamani": time.time(),
            "training_mode": "offline_research",
            "live_prediction_enabled": False,
            "artifact_saved": False,
            "offline_artifact_quality_gate": artifact_quality_gate,
            "prediction_diagnostics": prediction_diagnostics,
            "model_schema_version": self.model_schema_version,
            "label_schema_version": self.label_schema_version,
            "feature_schema_version": provenance["feature_schema_version"],
            "feature_contract_id": provenance["feature_contract_id"],
            "outcome_contract_id": self.outcome_spec.contract_id,
            "split_contract_id": self.training_split_spec.contract_id,
            "feature_spec": self.feature_availability_spec.to_dict(),
            "outcome_spec": self.outcome_spec.to_dict(),
            "split_spec": self.training_split_spec.to_dict(),
            "sembol": sembol,
            "base_timeframe": provenance["base_timeframe"],
            "feature_sayisi": len(aktif_features),
            "feature_names": list(aktif_features),
            "algoritma": algoritma,
            "egitim_mum_sayisi": int(len(feature_ready)),
            "sinif_sayilari": sinif_sayilari.astype(int).tolist(),
            "walk_forward_skoru": round(float(kalite_skoru), 4),
            "cv_balanced_accuracy": round(float(cv_balanced_accuracy), 6),
            "cv_brier_score": round(float(cv_brier), 6),
            "cv_oof_rows": int(len(cv_targets)),
            "cv_fold_rows": cv_fold_rows,
            "recent_balanced_accuracy": round(
                float(recent_balanced_accuracy),
                6,
            ),
            "recent_brier_score": round(float(recent_brier), 6),
            "recent_holdout_rows": int(len(holdout_frame)),
            "recent_profitable_up_count": int(holdout_actual.sum()),
            "recent_neutral_count": int(
                (np.abs(gross_holdout_returns) < self.min_target_return).sum()
            ),
            "recent_signal_count": int(recent_strategy["signal_count"]),
            "recent_signal_win_rate": round(
                float(recent_strategy["win_rate"]),
                6,
            ),
            "recent_strategy_net_return": round(
                float(recent_strategy["net_return"]),
                8,
            ),
            "recent_strategy_profit_factor": (
                round(float(recent_strategy["profit_factor"]), 6)
                if math.isfinite(float(recent_strategy["profit_factor"]))
                else 999.0
            ),
            "recent_strategy_max_drawdown": round(
                float(recent_strategy["max_drawdown"]),
                8,
            ),
            "holdout_train_rows": int(len(holdout_train)),
            "holdout_purge_rows": int(len(holdout.purge_index)),
            "holdout_start": holdout_frame.index[0].isoformat(),
            "holdout_end": holdout_frame.index[-1].isoformat(),
            "calibration_a": round(float(calibration_a), 8),
            "calibration_b": round(float(calibration_b), 8),
            "target_min_return": self.min_target_return,
            "signal_threshold": self.signal_threshold,
            "round_trip_cost_rate": self.round_trip_cost_rate,
        }
        if is_crypto:
            meta.update(
                {
                    "coverage_contract_id": provenance["coverage_contract_id"],
                    "coverage_spec": self.feature_coverage_spec.to_dict(),
                    "feature_quality": provenance["feature_quality"],
                    "joint_available_rows": int(joint_rows),
                    "joint_training_start": training_frame.index[0].isoformat(),
                    "joint_training_end": training_frame.index[-1].isoformat(),
                }
            )

        self.son_egitim_meta = meta
        if not artifact_quality_gate["passed"]:
            raise ValueError(
                "V6 offline artifact kalite kapısı başarısız: "
                + "; ".join(artifact_quality_gate["reasons"])
            )

        model = self._siniflandirici_olustur(
            algoritma,
            final_targets,
            n_estimators=self.n_estimators,
        )
        model.fit(
            feature_ready[aktif_features].to_numpy(),
            final_targets,
        )
        meta["artifact_saved"] = True
        self._atomik_model_kaydet(model, model_file)
        self._atomik_json_kaydet(meta, meta_file)

        elapsed = time.time() - baslama_zamani
        print(
            f"[OK] {sembol} V6 OFFLINE MODEL HAZIR "
            f"(CV={cv_balanced_accuracy:.3f}, "
            f"holdout={recent_balanced_accuracy:.3f}, "
            f"süre={elapsed:.2f}s)"
        )
        return model

    def model_egit(self, sembol, df, is_crypto=True, algoritma="xgboost"):
        """
        Verilen DataFrame üzerinden XGBoost veya LightGBM modelini eğitir ve kaydeder.
        Walk-Forward Expanding Window validation ve Feature Importance analizi içerir.
        """
        if self.label_schema_version == 6:
            return self._v6_model_egit(
                sembol,
                df,
                is_crypto=is_crypto,
                algoritma=algoritma,
            )
        import time
        baslama_zamani = time.time()
        
        aktif_features = self.crypto_features if is_crypto else self.stock_features
        df_tum = self.df_hazirla(df, drop_neutral=False)
        df_tum = self._featureleri_dogrula(df_tum, aktif_features, hedef_gerekli=False)
        df_etiketli = df_tum.dropna(subset=['Hedef_Yön']).copy()
        df_etiketli['Hedef_Yön'] = df_etiketli['Hedef_Yön'].astype(int)

        if len(df_etiketli) < 350:
            raise ValueError(f"Eğitim için veri yetersiz: {len(df_etiketli)} etiketli mum (min 350)")

        X_all = df_etiketli[aktif_features].values
        y_all = df_etiketli['Hedef_Yön'].values

        if len(np.unique(y_all)) < 2:
            raise ValueError("Eğitim hedefi tek sınıfa düştü; model öğrenemez.")
        
        # ============================================================
        # WALK-FORWARD EXPANDING WINDOW VALIDATION
        # Modelin gerçekten öğrenip öğrenmediğini test eder
        # ============================================================
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import balanced_accuracy_score, brier_score_loss
        from sklearn.model_selection import TimeSeriesSplit

        holdout_size = min(200, max(80, len(df_tum) // 4))
        core_end = len(df_tum) - holdout_size
        df_core = df_tum.iloc[:core_end].dropna(subset=['Hedef_Yön']).copy()
        df_core['Hedef_Yön'] = df_core['Hedef_Yön'].astype(int)
        if len(df_core) < 200:
            raise ValueError(f"Walk-forward eğitim çekirdeği yetersiz: {len(df_core)} etiketli mum")

        X_core = df_core[aktif_features].values
        y_core = df_core['Hedef_Yön'].values
        val_skorlari = []
        cv_probabilities = []
        cv_targets = []

        if len(X_core) >= 180:
            tscv = TimeSeriesSplit(n_splits=3, gap=self.horizon_bars)
            for train_idx, test_idx in tscv.split(X_core):
                X_train_cv, X_test_cv = X_core[train_idx], X_core[test_idx]
                y_train_cv, y_test_cv = y_core[train_idx], y_core[test_idx]

                if len(X_train_cv) < 100 or len(X_test_cv) < 20 or len(np.unique(y_train_cv)) < 2:
                    continue

                if algoritma == "lightgbm":
                    import lightgbm as lgb
                    cv_model = lgb.LGBMClassifier(
                        n_estimators=100, max_depth=self.max_depth,
                        learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                        scale_pos_weight=self._sinif_agirligi(y_train_cv),
                        random_state=self.random_state, force_col_wise=True, verbose=-1
                    )
                else:
                    import xgboost as xgb
                    cv_model = xgb.XGBClassifier(
                        n_estimators=100, max_depth=self.max_depth,
                        learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                        scale_pos_weight=self._sinif_agirligi(y_train_cv),
                        random_state=self.random_state, eval_metric="logloss"
                    )
                cv_model.fit(X_train_cv, y_train_cv)
                cv_probability = cv_model.predict_proba(X_test_cv)[:, 1]
                skor = balanced_accuracy_score(y_test_cv, cv_probability >= 0.5)
                val_skorlari.append(skor)
                cv_probabilities.extend(cv_probability.tolist())
                cv_targets.extend(y_test_cv.tolist())

        ort_skor = (sum(val_skorlari) / len(val_skorlari)) if val_skorlari else 0.0
        calibration_a = 1.0
        calibration_b = 0.0
        if len(cv_probabilities) >= 50 and len(set(cv_targets)) == 2:
            calibrator = LogisticRegression(C=1.0, solver='lbfgs', random_state=self.random_state)
            calibrator.fit(self._logit(cv_probabilities).reshape(-1, 1), np.asarray(cv_targets))
            calibration_a = float(calibrator.coef_[0][0])
            calibration_b = float(calibrator.intercept_[0])

        # ============================================================
        # SON DÖNEM HOLDOUT TESTİ
        # ============================================================
        import xgboost as xgb

        # Holdout'tan hemen önceki ufuk kadar satırı purging ile eğitimden çıkar.
        holdout_train = df_tum.iloc[:max(0, core_end - self.horizon_bars)]
        holdout_train = holdout_train.dropna(subset=['Hedef_Yön']).copy()
        holdout_train['Hedef_Yön'] = holdout_train['Hedef_Yön'].astype(int)
        holdout_frame = df_tum.iloc[core_end:].copy()
        X_holdout_train = holdout_train[aktif_features].values
        y_holdout_train = holdout_train['Hedef_Yön'].values
        X_holdout = holdout_frame[aktif_features].values
        holdout_actual = (holdout_frame['Gelecek_Ret'].values >= self.min_target_return).astype(int)
        holdout_returns = holdout_frame['Gelecek_Ret'].values.astype(float)

        if algoritma == "lightgbm":
            import lightgbm as lgb
            holdout_model = lgb.LGBMClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                scale_pos_weight=self._sinif_agirligi(y_holdout_train),
                random_state=self.random_state,
                force_col_wise=True, verbose=-1
            )
        else:
            holdout_model = xgb.XGBClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                scale_pos_weight=self._sinif_agirligi(y_holdout_train),
                random_state=self.random_state,
                eval_metric="logloss",
            )
        holdout_model.fit(X_holdout_train, y_holdout_train)
        holdout_raw = holdout_model.predict_proba(X_holdout)[:, 1]
        holdout_prob = self._kalibrasyon_uygula(holdout_raw, calibration_a, calibration_b)
        recent_balanced_accuracy = balanced_accuracy_score(holdout_actual, holdout_prob >= 0.5)
        recent_brier = brier_score_loss(holdout_actual, holdout_prob)
        recent_strategy = self._strateji_metrikleri(holdout_prob, holdout_returns)
        kalite_skoru = min(ort_skor, recent_balanced_accuracy) if val_skorlari else recent_balanced_accuracy

        print(
            f"📊 [{sembol}] WF dengeli doğruluk %{ort_skor*100:.1f} | "
            f"son dönem %{recent_balanced_accuracy*100:.1f} | "
            f"sinyal={recent_strategy['signal_count']} | "
            f"net=%{recent_strategy['net_return']*100:+.2f}"
        )

        # Doğrulama tamamlandıktan sonra nihai model tüm etiketli veriyle eğitilir.
        X = X_all
        y = y_all

        sinif_sayilari = np.bincount(y.astype(int), minlength=2)
        if min(sinif_sayilari) == 0:
            raise ValueError(f"Eğitim seti tek sınıfa düştü: {sinif_sayilari.tolist()}")

        scale_pos_weight = float(sinif_sayilari[0] / max(sinif_sayilari[1], 1))
        
        if algoritma == "lightgbm":
            import lightgbm as lgb
            model = lgb.LGBMClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                scale_pos_weight=scale_pos_weight,
                random_state=self.random_state,
                force_col_wise=True, verbose=-1
            )
        else:
            model = xgb.XGBClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                scale_pos_weight=scale_pos_weight,
                random_state=self.random_state,
                eval_metric="logloss"
            )
        
        tip = "Kripto" if is_crypto else "Hisse"
        algo_ismi = "LightGBM" if algoritma == "lightgbm" else "XGBoost"
        print(f"⏳ {sembol} ({tip}) {algo_ismi} modeli eğitime alındı...")
        model.fit(X, y)
        
        # ============================================================
        # FEATURE IMPORTANCE (SHAP Proxy — Hangi feature en etkili?)
        # ============================================================
        try:
            importances = model.feature_importances_
            feat_imp = sorted(zip(aktif_features, importances), key=lambda x: x[1], reverse=True)
            top3 = feat_imp[:3]
            bottom2 = feat_imp[-2:]
            print(f"🧠 [{sembol}] En Etkili 3 Feature: {top3[0][0]} (%{top3[0][1]*100:.0f}), {top3[1][0]} (%{top3[1][1]*100:.0f}), {top3[2][0]} (%{top3[2][1]*100:.0f})")
            print(f"   En Zayıf 2 Feature: {bottom2[0][0]} (%{bottom2[0][1]*100:.0f}), {bottom2[1][0]} (%{bottom2[1][1]*100:.0f})")
        except:
            pass
        
        # İsmi kaydet (model yaşını da kaydet)
        safe_name = sembol.replace('/', '-')
        prefix = self.model_prefix if is_crypto else "stock_beyin"
        if algoritma == "lightgbm":
            prefix = "lgbm_" + prefix
        dosya_adi = f'{prefix}_{safe_name}.pkl'
        meta_dosya = f'{prefix}_{safe_name}_meta.json'
        
        self._atomik_model_kaydet(model, dosya_adi)
        
        # Model yaş takibi (otomatik yenileme için)
        try:
            meta = {
                'egitim_zamani': time.time(),
                'model_schema_version': self.model_schema_version,
                'sembol': sembol,
                'feature_sayisi': len(aktif_features),
                'feature_names': list(aktif_features),
                'algoritma': algoritma,
                'egitim_mum_sayisi': int(len(X)),
                'sinif_sayilari': sinif_sayilari.astype(int).tolist(),
                'walk_forward_skoru': round(float(kalite_skoru), 4),
                'cv_balanced_accuracy': round(float(ort_skor), 6),
                'recent_balanced_accuracy': round(float(recent_balanced_accuracy), 6),
                'recent_brier_score': round(float(recent_brier), 6),
                'recent_holdout_rows': int(len(holdout_frame)),
                'recent_profitable_up_count': int(holdout_actual.sum()),
                'recent_neutral_count': int((np.abs(holdout_returns) < self.min_target_return).sum()),
                'recent_signal_count': int(recent_strategy['signal_count']),
                'recent_signal_win_rate': round(float(recent_strategy['win_rate']), 6),
                'recent_strategy_net_return': round(float(recent_strategy['net_return']), 8),
                'recent_strategy_profit_factor': (
                    round(float(recent_strategy['profit_factor']), 6)
                    if math.isfinite(float(recent_strategy['profit_factor'])) else 999.0
                ),
                'recent_strategy_max_drawdown': round(float(recent_strategy['max_drawdown']), 8),
                'calibration_a': round(calibration_a, 8),
                'calibration_b': round(calibration_b, 8),
                'target_min_return': self.min_target_return,
                'signal_threshold': self.signal_threshold,
                'round_trip_cost_rate': self.round_trip_cost_rate,
            }
            self._atomik_json_kaydet(meta, meta_dosya)
        except:
            pass
        
        gecen_sure = time.time() - baslama_zamani
        print(f"✅ {sembol} DİNAMİK MODEL HAZIR (Süre: {gecen_sure:.2f} Saniye)")
        return model

    def model_bayat_mi(self, sembol, is_crypto=True, max_yas_saat=24, algoritma="xgboost"):
        """Model dosyasının yaşını kontrol eder. 24 saatten eskiyse True döner."""
        import time, json
        safe_name = sembol.replace('/', '-')
        prefix = self.model_prefix if is_crypto else "stock_beyin"
        if algoritma == "lightgbm":
            prefix = "lgbm_" + prefix
        meta_dosya = f'{prefix}_{safe_name}_meta.json'
        aktif_features = self.crypto_features if is_crypto else self.stock_features
        
        try:
            with open(meta_dosya, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            if int(meta.get('model_schema_version') or 0) != self.model_schema_version:
                return True
            if int(meta.get('feature_sayisi') or 0) != len(aktif_features):
                return True
            if list(meta.get('feature_names') or []) != list(aktif_features):
                return True
            if str(meta.get('algoritma') or 'xgboost') != algoritma:
                return True
            yas_saat = (time.time() - meta['egitim_zamani']) / 3600
            return yas_saat > max_yas_saat
        except:
            return True  # Meta yoksa bayat kabul et

    def tahmin_et(self, sembol, df, is_crypto=True, algoritma="xgboost"):
        """
        Önceden eğitilmiş modeli yükler ve gelen ANLIK veri (df) üzerinden son satırı okuyarak tahminde bulunur.
        Model dosyası yoksa veya 24 saatten eskiyse otomatik olarak yeniden eğitir (Auto-Train).
        Dönüş: Tahmin Olasılığı (Float, 0.0 ile 1.0 arası)
        """
        if self.label_schema_version == 6:
            raise RuntimeError(
                "V6 tahmin yolu henüz etkin değil; doğrulanmamış model "
                "artefaktı yüklenemez."
            )
        safe_name = sembol.replace('/', '-')
        prefix = self.model_prefix if is_crypto else "stock_beyin"
        if algoritma == "lightgbm":
            prefix = "lgbm_" + prefix
        model_adi = f'{prefix}_{safe_name}.pkl'
        aktif_features = self.crypto_features if is_crypto else self.stock_features
        
        model = None
        
        # Model bayatsa yeniden eğit (Otomatik 24 saatlik yenileme)
        if self.model_bayat_mi(sembol, is_crypto, algoritma=algoritma):
            try:
                print(f"🔄 [{sembol}] Model 24 saatten eski, yeniden eğitiliyor...")
                model = self.model_egit(sembol, df.copy(), is_crypto, algoritma=algoritma)
            except Exception as e:
                print(f"⚠️ {sembol} model yenileme başarısız, eski model kullanılacak: {e}")
        
        if model is None:
            try:
                import joblib
                model = joblib.load(model_adi)
            except:
                try:
                    model = self.model_egit(sembol, df.copy(), is_crypto, algoritma=algoritma)
                except Exception as e:
                    print(f"⚠️ {sembol} model eğitimi başarısız: {e}")
                    return None
            
        if model is None:
            return None

        model_feature_sayisi = getattr(model, 'n_features_in_', None)
        if model_feature_sayisi is not None and int(model_feature_sayisi) != len(aktif_features):
            print(
                f"⚠️ {sembol} model şeması uyumsuz "
                f"(model={model_feature_sayisi}, beklenen={len(aktif_features)}); "
                "tek sefer yeniden eğitiliyor."
            )
            try:
                model = self.model_egit(
                    sembol,
                    df.copy(),
                    is_crypto,
                    algoritma=algoritma,
                )
            except Exception as e:
                print(f"⚠️ {sembol} şema yenilemesi başarısız: {e}")
                return None
            
        # Son satırdaki canlı teknik göstergeleri al
        aktif_features = self.crypto_features if is_crypto else self.stock_features
        try:
            eksik = [f for f in aktif_features if f not in df.columns]
            if eksik:
                print(f"⚠️ {sembol} tahmin iptal: eksik feature kolonları: {eksik}")
                return None

            giris_df = df[aktif_features].tail(1).copy()
            for kolon in aktif_features:
                giris_df[kolon] = pd.to_numeric(giris_df[kolon], errors='coerce')
            giris_df.replace([np.inf, -np.inf], np.nan, inplace=True)
            if giris_df.isna().any(axis=None):
                print(f"⚠️ {sembol} tahmin iptal: son feature satırında geçersiz değer var.")
                return None

            giris = giris_df.values
            olasiliklar = model.predict_proba(giris)
        except Exception as e:
            print(f"⚠️ {sembol} model/feature uyumsuzluğu: {e}")
            return None
        
        # Ham ağaç olasılığını yalnızca zaman sıralı doğrulamadan öğrenilen
        # katsayılarla kalibre et; eski modeller katsayı yoksa ham değeri kullanır.
        ham_olasilik = float(olasiliklar[0][1])
        olasilik = ham_olasilik
        try:
            meta_adi = model_adi.replace('.pkl', '_meta.json')
            with open(meta_adi, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            olasilik = float(self._kalibrasyon_uygula(
                [ham_olasilik],
                meta.get('calibration_a', 1.0),
                meta.get('calibration_b', 0.0),
            )[0])
        except Exception:
            olasilik = ham_olasilik
        self._tahmin_aciklamasi_olustur(sembol, model, aktif_features, giris_df, olasilik, model_adi)
        self.son_tahmin_aciklama[sembol]['ham_olasilik'] = ham_olasilik
        return olasilik
