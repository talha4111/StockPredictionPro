import pandas as pd
import pandas_ta as ta
import numpy as np
import ccxt
import time
from external_metric_store import (
    ExternalMetricSnapshotStore,
    SnapshotIntegrityError,
)
from model_contract import FeatureAvailabilitySpec, FeatureCoverageSpec

# --- CCXT Global API ---
borsa_api = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}})
try: borsa_api.load_markets()
except: pass

_V5_FEATURE_SCHEMA = 5
_V6_FEATURE_SCHEMA = 6
_V6_FEATURE_AVAILABILITY = FeatureAvailabilitySpec(
    schema_version=_V6_FEATURE_SCHEMA,
    base_timeframe='15m',
)
_V6_FEATURE_COVERAGE = FeatureCoverageSpec(
    schema_version=_V6_FEATURE_SCHEMA,
    base_timeframe='15m',
)
_V6_EXTERNAL_METRIC_STORE = ExternalMetricSnapshotStore()
_BINANCE_OI_RETENTION_MS = 29 * 24 * 60 * 60 * 1000


def _v6_get_feature_availability(timeframe='15m'):
    tf = str(timeframe or '15m')
    if tf == '15m':
        return _V6_FEATURE_AVAILABILITY
    return FeatureAvailabilitySpec(schema_version=_V6_FEATURE_SCHEMA, base_timeframe=tf)


def _v6_get_feature_coverage(timeframe='15m'):
    tf = str(timeframe or '15m')
    if tf == '15m':
        return _V6_FEATURE_COVERAGE
    min_joint = 300 if tf != '15m' else 1000
    return FeatureCoverageSpec(
        schema_version=_V6_FEATURE_SCHEMA,
        base_timeframe=tf,
        min_joint_available_bars=min_joint,
    )


def _feature_schema_dogrula(feature_schema_version):
    try:
        version = int(feature_schema_version)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Geçersiz feature schema version: {feature_schema_version!r}"
        ) from exc
    if version not in (_V5_FEATURE_SCHEMA, _V6_FEATURE_SCHEMA):
        raise ValueError(
            f"Desteklenmeyen feature schema version: {version}; "
            f"izin verilenler: {_V5_FEATURE_SCHEMA}, {_V6_FEATURE_SCHEMA}"
        )
    return version


def _feature_provenance_ekle(
    df,
    *,
    feature_schema_version,
    base_timeframe,
    feature_quality=None,
):
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df pandas DataFrame olmalıdır.")
    feature_schema_version = _feature_schema_dogrula(feature_schema_version)
    df.attrs['feature_schema_version'] = feature_schema_version
    df.attrs['base_timeframe'] = str(base_timeframe)
    avail = _v6_get_feature_availability(base_timeframe)
    cov = _v6_get_feature_coverage(base_timeframe)
    df.attrs['feature_contract_id'] = (
        avail.contract_id
        if feature_schema_version == _V6_FEATURE_SCHEMA
        else None
    )
    df.attrs['coverage_contract_id'] = (
        cov.contract_id
        if feature_schema_version == _V6_FEATURE_SCHEMA
        else None
    )
    df.attrs['feature_quality'] = (
        dict(feature_quality or {})
        if feature_schema_version == _V6_FEATURE_SCHEMA
        else {}
    )
    return df


def _ccxt_veri_getir(coin, timeframe='15m', limit=1000, max_pages=6):
    for deneme in range(3):
        try:
            hedef_limit = max(2, int(limit))
            # Canlı çağrılar varsayılan altı sayfada kalır. Araştırma araçları
            # tarihçe isteğini açıkça büyütebilir; üst sınır rate-limit
            # korumasını korur.
            page_cap = min(32, max(1, int(max_pages)))
            parca_limit = min(1000, hedef_limit)
            try:
                timeframe_ms = int(borsa_api.parse_timeframe(timeframe) * 1000)
            except Exception:
                timeframe_ms = {
                    '15m': 15 * 60 * 1000,
                    '1h': 60 * 60 * 1000,
                    '4h': 4 * 60 * 60 * 1000,
                }.get(timeframe, 15 * 60 * 1000)

            since = int(time.time() * 1000) - (hedef_limit * timeframe_ms)
            bars = []
            for _ in range(page_cap):
                kalan = hedef_limit - len(bars)
                if kalan <= 0:
                    break
                parca = borsa_api.fetch_ohlcv(
                    coin, timeframe, since=since, limit=min(parca_limit, kalan)
                )
                if not parca:
                    break
                bars.extend(parca)
                son_zaman = int(parca[-1][0])
                sonraki_since = son_zaman + timeframe_ms
                if len(parca) < parca_limit or sonraki_since <= since:
                    break
                since = sonraki_since

            if not bars:
                raise RuntimeError('OHLCV verisi bos dondu')
            benzersiz_bars = {int(bar[0]): bar for bar in bars}
            bars = [benzersiz_bars[key] for key in sorted(benzersiz_bars)]
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df[~df.index.duplicated(keep='last')].sort_index()
            # Borsa son mumu tamamlanmadan döndürebilir; tamamlanmamış mum
            # hem hedefte hem üst zaman dilimi feature'larında kullanılmaz.
            return df.iloc[:-1].copy() if len(df) > 1 else df.iloc[0:0].copy()
        except Exception as e:
            if deneme == 2:
                print(f"❌ ccxt Hatası ({coin}): {e}")
                return None
            time.sleep(2)


def _dis_metrik_serisi(rows, *, value_columns, name):
    if not rows:
        return pd.Series(
            dtype=float,
            index=pd.DatetimeIndex([], dtype='datetime64[ns]'),
            name=name,
        )
    frame = pd.DataFrame(rows)
    if 'timestamp' not in frame.columns:
        return pd.Series(
            dtype=float,
            index=pd.DatetimeIndex([], dtype='datetime64[ns]'),
            name=name,
        )
    value_column = next(
        (column for column in value_columns if column in frame.columns),
        None,
    )
    if value_column is None:
        return pd.Series(
            dtype=float,
            index=pd.DatetimeIndex([], dtype='datetime64[ns]'),
            name=name,
        )
    timestamp = pd.to_datetime(frame['timestamp'], unit='ms', errors='coerce')
    value = pd.to_numeric(frame[value_column], errors='coerce')
    series = pd.Series(value.to_numpy(), index=timestamp, name=name, dtype=float)
    series = series[~series.index.isna() & series.notna()]
    series = series[~series.index.duplicated(keep='last')].sort_index()
    return series


def _sayfali_dis_metrik_getir(
    fetch_page,
    *,
    since_ms,
    until_ms,
    page_limit,
    max_calls,
    value_columns,
    name,
):
    since_ms = int(since_ms)
    until_ms = int(until_ms)
    page_limit = int(page_limit)
    max_calls = int(max_calls)
    if since_ms > until_ms:
        raise ValueError("Pagination since_ms, until_ms değerini aşamaz.")
    if page_limit < 1 or max_calls < 1:
        raise ValueError("Pagination limitleri pozitif olmalıdır.")

    cursor = since_ms
    pages = []
    calls = 0
    completed = False
    last_error = None
    while calls < max_calls and cursor <= until_ms:
        calls += 1
        try:
            raw_page = fetch_page(cursor, page_limit)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            break
        raw_page = list(raw_page or [])
        if not raw_page:
            completed = True
            break
        page = _dis_metrik_serisi(
            raw_page,
            value_columns=value_columns,
            name=name,
        )
        if page.empty:
            last_error = "API sayfası geçerli timestamp/değer içermiyor."
            break
        raw_last_ms = int(page.index[-1].value // 1_000_000)
        page_ms = np.asarray(
            [
                int(timestamp.value // 1_000_000)
                for timestamp in page.index
            ],
            dtype="int64",
        )
        page = page.loc[
            (page_ms >= since_ms)
            & (page_ms <= until_ms)
        ]
        if raw_last_ms < cursor:
            last_error = "API pagination cursor ilerlemedi."
            break
        if not page.empty:
            pages.append(page)
        next_cursor = raw_last_ms + 1
        if raw_last_ms >= until_ms or len(raw_page) < page_limit:
            cursor = next_cursor
            completed = True
            break
        if next_cursor <= cursor:
            last_error = "API pagination cursor ilerlemedi."
            break
        cursor = next_cursor

    if pages:
        combined = pd.concat(pages)
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    else:
        combined = pd.Series(
            dtype=float,
            index=pd.DatetimeIndex([], dtype="datetime64[ns]"),
            name=name,
        )
    return combined, {
        "calls": calls,
        "completed": bool(completed),
        "last_error": last_error,
        "next_since_ms": int(cursor),
        "fetched_records": int(len(combined)),
        "page_limit": page_limit,
        "max_calls": max_calls,
    }


def _v6_dis_metrik_gecmisi(
    symbol,
    target_index,
    *,
    metric,
    timeframe,
    exchange=None,
    store=None,
):
    target_index = pd.DatetimeIndex(target_index)
    if target_index.empty:
        raise ValueError("V6 dış metrik hedef indexi boş olamaz.")
    if not target_index.is_monotonic_increasing or target_index.has_duplicates:
        raise ValueError("V6 dış metrik hedef indexi artan ve benzersiz olmalıdır.")

    exchange = exchange or borsa_api
    store = store or _V6_EXTERNAL_METRIC_STORE
    requested_since_ms = int(target_index[0].value // 1_000_000)
    until_ms = int(
        (target_index[-1] + _V6_FEATURE_COVERAGE.base_delta).value
        // 1_000_000
    )
    if metric == "open_interest":
        effective_since_ms = max(
            requested_since_ms,
            until_ms - _BINANCE_OI_RETENTION_MS,
        )
        page_limit = 500
        max_calls = 10
        value_columns = (
            "openInterestValue",
            "quoteVolume",
            "openInterestAmount",
        )

        def fetch_page(cursor, limit):
            return exchange.fetch_open_interest_history(
                symbol,
                timeframe=timeframe,
                since=cursor,
                limit=limit,
            )

    elif metric == "funding_rate":
        effective_since_ms = requested_since_ms
        page_limit = 1000
        max_calls = 4
        value_columns = ("fundingRate",)

        def fetch_page(cursor, limit):
            return exchange.fetch_funding_rate_history(
                symbol,
                since=cursor,
                limit=limit,
            )

    else:
        raise ValueError(f"Desteklenmeyen dış metrik: {metric!r}")

    integrity_error = None
    try:
        snapshot = store.load(symbol, metric, timeframe)
    except SnapshotIntegrityError as exc:
        integrity_error = str(exc)
        snapshot = None

    cached = (
        snapshot.series
        if snapshot is not None
        else pd.Series(
            dtype=float,
            index=pd.DatetimeIndex([], dtype="datetime64[ns]"),
            name=metric,
        )
    )
    previous_metadata = snapshot.metadata if snapshot is not None else {}
    previous_floor = previous_metadata.get("effective_since_ms")
    previous_complete = bool(previous_metadata.get("pagination_complete"))
    if (
        not cached.empty
        and previous_complete
        and previous_floor is not None
        and int(previous_floor) <= effective_since_ms
    ):
        fetch_since_ms = max(
            effective_since_ms,
            int(cached.index[-1].value // 1_000_000) + 1,
        )
    elif not cached.empty and previous_floor is not None:
        if int(previous_floor) <= effective_since_ms:
            fetch_since_ms = int(cached.index[-1].value // 1_000_000) + 1
        else:
            fetch_since_ms = effective_since_ms
    else:
        fetch_since_ms = effective_since_ms

    if fetch_since_ms <= until_ms:
        fetched, pagination = _sayfali_dis_metrik_getir(
            fetch_page,
            since_ms=fetch_since_ms,
            until_ms=until_ms,
            page_limit=page_limit,
            max_calls=max_calls,
            value_columns=value_columns,
            name=metric,
        )
    else:
        fetched = pd.Series(
            dtype=float,
            index=pd.DatetimeIndex([], dtype="datetime64[ns]"),
            name=metric,
        )
        pagination = {
            "calls": 0,
            "completed": True,
            "last_error": None,
            "next_since_ms": int(fetch_since_ms),
            "fetched_records": 0,
            "page_limit": page_limit,
            "max_calls": max_calls,
        }

    combined = pd.concat([cached, fetched])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined = combined.loc[
        (combined.index >= pd.to_datetime(effective_since_ms, unit="ms"))
        & (combined.index <= pd.to_datetime(until_ms, unit="ms"))
    ]
    metadata = {
        "requested_since_ms": requested_since_ms,
        "effective_since_ms": effective_since_ms,
        "until_ms": until_ms,
        "pagination_complete": bool(pagination["completed"]),
        "last_error": pagination["last_error"],
        "integrity_error": integrity_error,
        "last_fetch_calls": int(pagination["calls"]),
        "last_fetch_records": int(pagination["fetched_records"]),
    }
    snapshot_saved = False
    if integrity_error is None:
        try:
            saved = store.update(
                symbol,
                metric,
                timeframe,
                fetched,
                metadata=metadata,
                retain_since_ms=effective_since_ms,
            )
            combined = saved.series.loc[
                (saved.series.index >= pd.to_datetime(effective_since_ms, unit="ms"))
                & (saved.series.index <= pd.to_datetime(until_ms, unit="ms"))
            ]
            snapshot_saved = True
        except (OSError, SnapshotIntegrityError, ValueError) as exc:
            metadata["snapshot_error"] = f"{type(exc).__name__}: {exc}"
    metadata.update(
        {
            "snapshot_saved": snapshot_saved,
            "cached_records": int(len(cached)),
            "returned_records": int(len(combined)),
        }
    )
    combined.name = metric
    return combined, metadata


def veri_getir_dortlu(
    hedef_coin,
    referans_coin,
    timeframe='15m',
    feature_schema_version=_V5_FEATURE_SCHEMA,
    history_limit=4000,
    max_ohlcv_pages=6,
):
    try:
        feature_schema_version = _feature_schema_dogrula(feature_schema_version)
        # 1. Veri İndirme (ccxt)
        df_hedef = _ccxt_veri_getir(
            hedef_coin,
            timeframe=timeframe,
            limit=history_limit,
            max_pages=max_ohlcv_pages,
        )
        df_ref = _ccxt_veri_getir(
            referans_coin,
            timeframe=timeframe,
            limit=history_limit,
            max_pages=max_ohlcv_pages,
        )
        
        if df_hedef is None or df_ref is None or df_hedef.empty or df_ref.empty:
            return None

        # 3. SÜTUN HAZIRLAMA (Analiz motoru için 'open' sütunu ŞARTTIR!)
        df = df_hedef[['open', 'high', 'low', 'close', 'volume']].copy()
        df.rename(columns={'close': 'Hedef_Close'}, inplace=True)
        
        # Ref_Close hizalaması (ffill saniyelik boşlukları korur)
        ref_series = df_ref['close'].reindex(df.index, method='ffill')
        df['Ref_Close'] = ref_series.values

        # --- Epsilon Yaması (Sıfıra Bölünme / RuntimeWarning Koruması) ---
        # Eğer bir mumda High ve Low eşitse (True Range 0), payda belirsizliği yüzünden CHOP ve Squeeze motoru çöker.
        # Bu yüzden çok ufak bir Epsilon (1e-9) sapması ekliyoruz.
        mask_equal = (df['high'] == df['low'])
        df.loc[mask_equal, 'high'] += 1e-9
        df.loc[mask_equal, 'low'] -= 1e-9

        # 4. İndikatör Hesaplamaları
        df['RSI'] = df.ta.rsi(close='Hedef_Close', length=11)
        
        macd = df.ta.macd(close='Hedef_Close', fast=15, slow=26, signal=9)
        df['MACD'] = macd.iloc[:, 0] if macd is not None else 0
        
        df['ATR'] = df.ta.atr(high='high', low='low', close='Hedef_Close', length=14)
        
        adx = df.ta.adx(high='high', low='low', close='Hedef_Close', length=14)
        if adx is not None and not adx.empty:
            df['ADX'] = adx.iloc[:, 0].fillna(0)
            df['DMP'] = adx.iloc[:, 1].fillna(0)  # +DI (Pozitif Yön Göstergesi)
            df['DMN'] = adx.iloc[:, 2].fillna(0)  # -DI (Negatif Yön Göstergesi)
        else:
            df['ADX'] = 0.0
            df['DMP'] = 0.0
            df['DMN'] = 0.0

        # Yeni Eklenen Kritik Sensörler
        df['OBV'] = df.ta.obv(close=df['Hedef_Close'], volume=df['volume'])
        
        bbands = df.ta.bbands(close=df['Hedef_Close'], length=20)
        df['BB_Width'] = bbands.iloc[:, 3] if bbands is not None else 0
        df['BB_Width_Mean_100'] = df['BB_Width'].rolling(window=50).mean()  # Pencere 100->50 (Daha reaktif)
        
        df['MFI'] = df.ta.mfi(high=df['high'], low=df['low'], close=df['Hedef_Close'], volume=df['volume'], length=14)

        # --- Hacim Profili (Volume Profile) / VWAP Analizi ---
        vwap = df.ta.vwap(high=df['high'], low=df['low'], close=df['Hedef_Close'], volume=df['volume'])
        df['VWAP'] = vwap if vwap is not None else df['Hedef_Close']
        df['VP_Sapma'] = (df['Hedef_Close'] - df['VWAP']) / df['VWAP']

        # --- YATAY PİYASA KALKANI (CHOP & SQUEEZE) ---
        chop = df.ta.chop(high=df['high'], low=df['low'], close=df['Hedef_Close'], length=14)
        df['CHOP'] = chop if chop is not None else 50.0

        sqz = df.ta.squeeze(high=df['high'], low=df['low'], close=df['Hedef_Close'], length=20, lazybear=True)
        if sqz is not None:
            on_col = [c for c in sqz.columns if 'ON' in c]
            df['Squeeze_ON'] = sqz[on_col[0]] if on_col else 0.0
        else:
            df['Squeeze_ON'] = 0.0

        # --- SÜRÜ PSİKOLOJİSİ (Funding Rate & Open Interest) ---
        df['Open_Interest'] = 0.0
        df['Funding_Rate'] = 0.0001
        oi_bars = []
        fr_bars = []
        oi_acquisition = {}
        funding_acquisition = {}
        if feature_schema_version == _V5_FEATURE_SCHEMA:
            try:
                oi_bars = borsa_api.fetch_open_interest_history(hedef_coin, timeframe=timeframe, limit=1000)
                if oi_bars:
                    oi_df = pd.DataFrame(oi_bars)
                    oi_df['timestamp'] = pd.to_datetime(oi_df['timestamp'], unit='ms')
                    oi_df.set_index('timestamp', inplace=True)
                    df['Open_Interest'] = oi_df['openInterestValue']
            except:
                pass

            try:
                fr_bars = borsa_api.fetch_funding_rate_history(hedef_coin, limit=100)
                if fr_bars:
                    fr_df = pd.DataFrame(fr_bars)
                    fr_df['timestamp'] = pd.to_datetime(fr_df['timestamp'], unit='ms')
                    fr_df.set_index('timestamp', inplace=True)
                    df['Funding_Rate'] = fr_df['fundingRate']
            except:
                pass
        else:
            try:
                oi_source, oi_acquisition = _v6_dis_metrik_gecmisi(
                    hedef_coin,
                    df.index,
                    metric='open_interest',
                    timeframe=timeframe,
                )
            except Exception as exc:
                oi_source = pd.Series(dtype=float, name='open_interest')
                oi_acquisition = {
                    'last_error': f'{type(exc).__name__}: {exc}',
                    'snapshot_saved': False,
                    'returned_records': 0,
                }
            try:
                funding_source, funding_acquisition = _v6_dis_metrik_gecmisi(
                    hedef_coin,
                    df.index,
                    metric='funding_rate',
                    timeframe='events',
                )
            except Exception as exc:
                funding_source = pd.Series(dtype=float, name='funding_rate')
                funding_acquisition = {
                    'last_error': f'{type(exc).__name__}: {exc}',
                    'snapshot_saved': False,
                    'returned_records': 0,
                }

        oi_aligned = None
        funding_aligned = None
        if feature_schema_version == _V6_FEATURE_SCHEMA:
            coverage_spec = _v6_get_feature_coverage(timeframe)
            oi_source = oi_source.rename('Open_Interest')
            funding_source = funding_source.rename('Funding_Rate')
            oi_aligned = coverage_spec.align_observations(
                oi_source,
                df.index,
                feature_name='Open_Interest',
                max_staleness_bars=2,
                baseline_value=0.0,
            )
            funding_aligned = coverage_spec.align_observations(
                funding_source,
                df.index,
                feature_name='Funding_Rate',
                max_staleness_bars=36,
                baseline_value=0.0001,
            )
            for column in oi_aligned.columns:
                df[column] = oi_aligned[column]
            for column in funding_aligned.columns:
                df[column] = funding_aligned[column]
        else:
            # V5 davranışı: ilk gerçek gözleme kadar nötr baseline kullan.
            df['Open_Interest'] = df['Open_Interest'].ffill().fillna(0)
            df['Funding_Rate'] = df['Funding_Rate'].ffill().fillna(0.0001)

        # 5. Delta (Değişim) ve Korelasyon
        df['Hedef_Ret'] = df['Hedef_Close'].pct_change().fillna(0)
        df['Ref_Ret'] = df['Ref_Close'].pct_change().fillna(0)
        df['Vol_Ret'] = df['volume'].pct_change().fillna(0)
        df['Korelasyon'] = df['Hedef_Ret'].rolling(window=14).corr(df['Ref_Ret']).fillna(0)
        df['BTC_Korelasyon'] = df['Hedef_Ret'].rolling(window=30).corr(df['Ref_Ret']).fillna(0)

        # --- TREND GÜCÜ (EMA Slope - Modelin trend yönünü öğrenmesi için) ---
        ema20 = df.ta.ema(close='Hedef_Close', length=20)
        if ema20 is not None:
            df['EMA_Slope'] = ema20.pct_change(periods=5).fillna(0) * 100  # Son 5 mumda EMA değişim yüzdesi
        else:
            df['EMA_Slope'] = 0.0

        # --- KRİZ İNDİKATÖRÜ (Gerçekçi - son 10 mumda %3+ düşüş varsa) ---
        df['Kriz'] = np.where(df['Hedef_Close'].pct_change(periods=10) < -0.03, 1.0, 0.0)

        # ============================================================
        # 🆕 YENİ PRO FEATURE'LAR (Quant Standart v2.0)
        # ============================================================
        # 1. Lagged Return: Bir önceki mumun getirisi (Otokorelasyon/Momentum etkisi)
        df['Lagged_Ret_1'] = df['Hedef_Ret'].shift(1).fillna(0)

        # 2. Rolling Volatility: 20 mumda getiri standart sapması (Piyasa rejim tespiti)
        df['Volatility_20'] = df['Hedef_Ret'].rolling(window=20).std().fillna(0)

        # 3. Volume Z-Score: Anlık hacmin normalden ne kadar saptığı (Balina tespiti)
        vol_mean = df['volume'].rolling(window=50).mean()
        vol_std = df['volume'].rolling(window=50).std()
        df['Volume_ZScore'] = ((df['volume'] - vol_mean) / vol_std.replace(0, 1)).fillna(0)

        # 4. RSI 4H: Büyük resim momentum (4 saatlik RSI değeri 15m frame'e inject edilir)
        df['RSI_4H'] = _rsi_4h_serisi_getir(
            hedef_coin,
            df.index,
            feature_schema_version=feature_schema_version,
        )
        # ============================================================
        # 🆕 SPRINT 1: MULTI-TIMEFRAME FEATURES (1H + 4H → 15m inject)
        # ============================================================
        mtf = _multi_tf_serileri_getir(
            hedef_coin,
            df.index,
            feature_schema_version=feature_schema_version,
        )
        df['RSI_1H'] = mtf.get('RSI_1H', 50.0)
        df['EMA_Slope_1H'] = mtf.get('EMA_Slope_1H', 0.0)
        df['ADX_4H'] = mtf.get('ADX_4H', 25.0)
        df['Volume_Trend_4H'] = mtf.get('Volume_Trend_4H', 0.0)
        df['Trend_Alignment'] = mtf.get('Trend_Alignment', 0.0)

        # ============================================================
        # 👑 YENİ NESİL MİKROYAPI VE REJİM SENSÖRLERİ (Quant v3.0)
        # ============================================================
        
        # 5. ATR Z-Score: Piyasanın KENDİ geçmişine göre Volatilite Rejimi
        atr_mean = df['ATR'].rolling(window=50).mean()
        atr_std = df['ATR'].rolling(window=50).std()
        df['ATR_ZScore'] = ((df['ATR'] - atr_mean) / atr_std.replace(0, 1e-9)).fillna(0)

        # 6. Alım Baskısı Proxisi (Intrabar Buy Pressure)
        # Kapanış mumun üst ucuna yakınsa pozitif baskı, alt ucuna yakınsa negatif baskı.
        high_low_range = df['high'] - df['low']
        buy_pressure = (df['Hedef_Close'] - df['low']) / high_low_range.replace(0, 1e-9)
        df['Buy_Pressure'] = (buy_pressure * 2) - 1.0  # -1.0 (Tam Ayı) ile +1.0 (Tam Boğa) arası

        # --- YENİ EKLENEN: TAKER RATIO SİMÜLASYONU ---
        # Taker_Ratio: Hacmin alış ağırlıklı mı satış ağırlıklı mı olduğunu tahmin eder (0.0 ile 1.0 arası)
        fiyat_degisimi = df['Hedef_Close'] - df['open']
        raw_taker = (fiyat_degisimi / high_low_range.replace(0, 1e-9) + 1.0) / 2.0
        df['Taker_Ratio'] = raw_taker.clip(0.0, 1.0).fillna(0.5)

        # 7. Funding Rate İvmesi (Delta)
        # Sadece mevcut Funding değil, yönü de önemlidir. Herkes LONG açmaya başladığında hızla artar.
        funding_delta = df['Funding_Rate'].diff(periods=4)
        if feature_schema_version == _V6_FEATURE_SCHEMA:
            funding_pair_available = (
                df['Funding_Rate_Available'].astype(bool)
                & df['Funding_Rate_Available'].shift(4).fillna(0).astype(bool)
            )
            funding_delta = funding_delta.where(
                funding_pair_available,
                0.0,
            )
        df['Funding_Delta'] = funding_delta.fillna(0)

        # 8. Zamansal Döngüler (Cyclical Time Embeddings)
        # Modelin Asya seansı ile ABD seansı arasındaki farkı matematiksel olarak anlaması için (Sin/Cos dönüşümü)
        df['Hour_Sin'] = np.sin(2 * np.pi * df.index.hour / 24.0)
        df['Hour_Cos'] = np.cos(2 * np.pi * df.index.hour / 24.0)

        # 6. Hatalı Verileri Temizle
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.dropna(inplace=True)
        feature_quality = {}
        if feature_schema_version == _V6_FEATURE_SCHEMA:
            oi_source_count = int(
                oi_aligned.attrs['quality_report']['source_observations']
            )
            funding_source_count = int(
                funding_aligned.attrs['quality_report']['source_observations']
            )
            feature_quality = {
                'Open_Interest': coverage_spec.quality_report(
                    oi_aligned.loc[df.index],
                    feature_name='Open_Interest',
                    max_staleness_bars=2,
                    source_observations=oi_source_count,
                ),
                'Funding_Rate': coverage_spec.quality_report(
                    funding_aligned.loc[df.index],
                    feature_name='Funding_Rate',
                    max_staleness_bars=36,
                    source_observations=funding_source_count,
                ),
            }
            feature_quality['Open_Interest']['acquisition'] = oi_acquisition
            feature_quality['Funding_Rate']['acquisition'] = (
                funding_acquisition
            )
        _feature_provenance_ekle(
            df,
            feature_schema_version=feature_schema_version,
            base_timeframe=timeframe,
            feature_quality=feature_quality,
        )
        
        return df

    except Exception as e:
        print(f"❌ Veri Çekme Hatası ({hedef_coin}): {e}")
        return None

def _rsi_4h_getir(coin):
    """4 saatlik RSI değerini scalar olarak döndürür (büyük resim momentum)."""
    try:
        df_4h = _ccxt_veri_getir(coin, timeframe='4h', limit=50)
        if df_4h is None or df_4h.empty:
            return 50.0  # Nötr fallback
        rsi_4h = ta.rsi(df_4h['close'], length=14)
        if rsi_4h is not None and not rsi_4h.empty:
            return float(rsi_4h.iloc[-1])
        return 50.0
    except:
        return 50.0

def _multi_tf_getir(coin):
    """
    Sprint 1: Çoklu Zaman Dilimi (Multi-Timeframe) sensörleri.
    1H ve 4H verilerinden türetilen özellikleri 15m frame'e scalar olarak enjekte eder.
    """
    sonuc = {
        'RSI_1H': 50.0, 'EMA_Slope_1H': 0.0,
        'ADX_4H': 25.0, 'Volume_Trend_4H': 0.0,
        'Trend_Alignment': 0.0
    }
    try:
        # --- 1H Verisi ---
        df_1h = _ccxt_veri_getir(coin, timeframe='1h', limit=50)
        if df_1h is not None and not df_1h.empty:
            # 1H RSI
            rsi_1h = ta.rsi(df_1h['close'], length=14)
            if rsi_1h is not None and not rsi_1h.empty:
                sonuc['RSI_1H'] = float(rsi_1h.iloc[-1])
            # 1H EMA20 Slope (son 3 mumda eğim)
            ema20_1h = ta.ema(df_1h['close'], length=20)
            if ema20_1h is not None and len(ema20_1h) > 3:
                slope = (ema20_1h.iloc[-1] - ema20_1h.iloc[-3]) / ema20_1h.iloc[-3] * 100
                sonuc['EMA_Slope_1H'] = float(slope)

        # --- 4H Verisi ---
        df_4h = _ccxt_veri_getir(coin, timeframe='4h', limit=50)
        if df_4h is not None and not df_4h.empty:
            # 4H ADX
            adx_4h = df_4h.ta.adx(high='high', low='low', close='close', length=14)
            if adx_4h is not None and not adx_4h.empty:
                sonuc['ADX_4H'] = float(adx_4h.iloc[-1, 0])
            # 4H Volume Trend (son 5 mum vs önceki 5 mum hacim ortalaması)
            if len(df_4h) >= 10:
                son_5 = df_4h['volume'].iloc[-5:].mean()
                onceki_5 = df_4h['volume'].iloc[-10:-5].mean()
                sonuc['Volume_Trend_4H'] = float((son_5 / max(onceki_5, 1e-9)) - 1.0)
            # 4H EMA50 trend yönü
            ema50_4h = ta.ema(df_4h['close'], length=50)
            if ema50_4h is not None and not ema50_4h.empty:
                son_fiyat = df_4h['close'].iloc[-1]
                son_ema50 = ema50_4h.iloc[-1]
                # Trend Alignment: +1 (fiyat EMA üstü), -1 (fiyat EMA altı), 0 (nötr)
                mesafe_yuzde = ((son_fiyat - son_ema50) / son_ema50) * 100
                if mesafe_yuzde > 0.5:
                    sonuc['Trend_Alignment'] = 1.0
                elif mesafe_yuzde < -0.5:
                    sonuc['Trend_Alignment'] = -1.0
                else:
                    sonuc['Trend_Alignment'] = 0.0
    except Exception as e:
        pass  # Hata durumunda nötr değerler döner
    return sonuc

def _hizali_feature_serisi(
    frame,
    column,
    target_index,
    default,
    *,
    source_timeframe=None,
    target_timeframe='15m',
    feature_schema_version=_V5_FEATURE_SCHEMA,
):
    feature_schema_version = _feature_schema_dogrula(feature_schema_version)
    target_index = pd.DatetimeIndex(target_index)
    if frame is None or frame.empty or column not in frame.columns:
        return pd.Series(float(default), index=target_index, dtype=float)
    series = pd.to_numeric(frame[column], errors='coerce').replace([np.inf, -np.inf], np.nan)
    if feature_schema_version == _V6_FEATURE_SCHEMA:
        if not source_timeframe:
            raise ValueError("V6 MTF hizalaması source_timeframe gerektirir.")
        avail = _v6_get_feature_availability(target_timeframe)
        return avail.align_completed_feature(
            series,
            target_index,
            source_timeframe=source_timeframe,
            fill_value=float(default),
        )
    aligned = series.reindex(target_index, method='ffill')
    return aligned.fillna(float(default)).astype(float)


def _rsi_4h_serisi_getir(
    coin,
    target_index,
    *,
    feature_schema_version=_V5_FEATURE_SCHEMA,
):
    feature_schema_version = _feature_schema_dogrula(feature_schema_version)
    try:
        df_4h = _ccxt_veri_getir(coin, timeframe='4h', limit=1000)
        if df_4h is not None and not df_4h.empty:
            rsi = ta.rsi(df_4h['close'], length=14)
            if rsi is not None:
                return _hizali_feature_serisi(
                    pd.DataFrame({'RSI_4H': rsi}, index=df_4h.index),
                    'RSI_4H',
                    target_index,
                    50.0,
                    source_timeframe='4h',
                    feature_schema_version=feature_schema_version,
                )
    except Exception:
        pass
    return pd.Series(50.0, index=pd.DatetimeIndex(target_index), dtype=float)


def _multi_tf_serileri_getir(
    coin,
    target_index,
    *,
    feature_schema_version=_V5_FEATURE_SCHEMA,
):
    feature_schema_version = _feature_schema_dogrula(feature_schema_version)
    target_index = pd.DatetimeIndex(target_index)
    defaults = {
        'RSI_1H': 50.0,
        'EMA_Slope_1H': 0.0,
        'ADX_4H': 25.0,
        'Volume_Trend_4H': 0.0,
        'Trend_Alignment': 0.0,
    }
    features = {
        key: pd.Series(value, index=target_index, dtype=float)
        for key, value in defaults.items()
    }

    try:
        df_1h = _ccxt_veri_getir(coin, timeframe='1h', limit=1000)
        if df_1h is not None and not df_1h.empty:
            rsi_1h = ta.rsi(df_1h['close'], length=14)
            if rsi_1h is not None:
                features['RSI_1H'] = _hizali_feature_serisi(
                    pd.DataFrame({'value': rsi_1h}, index=df_1h.index),
                    'value',
                    target_index,
                    50.0,
                    source_timeframe='1h',
                    feature_schema_version=feature_schema_version,
                )
            ema20_1h = ta.ema(df_1h['close'], length=20)
            if ema20_1h is not None:
                slope_1h = ema20_1h.pct_change(periods=3) * 100.0
                features['EMA_Slope_1H'] = _hizali_feature_serisi(
                    pd.DataFrame({'value': slope_1h}, index=df_1h.index),
                    'value',
                    target_index,
                    0.0,
                    source_timeframe='1h',
                    feature_schema_version=feature_schema_version,
                )

        df_4h = _ccxt_veri_getir(coin, timeframe='4h', limit=1000)
        if df_4h is not None and not df_4h.empty:
            adx_4h = df_4h.ta.adx(
                high='high', low='low', close='close', length=14
            )
            if adx_4h is not None and not adx_4h.empty:
                features['ADX_4H'] = _hizali_feature_serisi(
                    pd.DataFrame({'value': adx_4h.iloc[:, 0]}, index=df_4h.index),
                    'value',
                    target_index,
                    25.0,
                    source_timeframe='4h',
                    feature_schema_version=feature_schema_version,
                )

            volume_mean = df_4h['volume'].rolling(window=5).mean()
            volume_trend = (volume_mean / volume_mean.shift(5)) - 1.0
            features['Volume_Trend_4H'] = _hizali_feature_serisi(
                pd.DataFrame({'value': volume_trend}, index=df_4h.index),
                'value',
                target_index,
                0.0,
                source_timeframe='4h',
                feature_schema_version=feature_schema_version,
            )

            ema50_4h = ta.ema(df_4h['close'], length=50)
            if ema50_4h is not None:
                distance = ((df_4h['close'] - ema50_4h) / ema50_4h) * 100.0
                alignment = np.where(distance > 0.5, 1.0, np.where(distance < -0.5, -1.0, 0.0))
                features['Trend_Alignment'] = _hizali_feature_serisi(
                    pd.DataFrame({'value': alignment}, index=df_4h.index),
                    'value',
                    target_index,
                    0.0,
                    source_timeframe='4h',
                    feature_schema_version=feature_schema_version,
                )
    except Exception:
        pass
    return features


def emir_defteri_analizi(coin):
    """
    Sprint 3: Emir Defteri (Order Book) Dengesizlik Analizi.
    Bid/Ask hacim oranını hesaplayarak balinaların yönünü tespit eder.
    Dönüş: -1.0 (satıcılar baskın) ile +1.0 (alıcılar baskın) arası float
    """
    try:
        ob = borsa_api.fetch_order_book(coin, limit=20)
        if not ob or not ob.get('bids') or not ob.get('asks'):
            return 0.0
        bid_vol = sum(b[1] for b in ob['bids'][:20])
        ask_vol = sum(a[1] for a in ob['asks'][:20])
        if ask_vol == 0:
            return 1.0
        oran = bid_vol / ask_vol
        # Normalize: 0.5 ile 2.0 arasını -1.0 ile +1.0 arasına map et
        normalized = max(-1.0, min(1.0, (oran - 1.0) * 2.0))
        return round(normalized, 4)
    except:
        return 0.0

def ana_trend_getir(coin):
    """
    4 Saatlik (4h) grafikte ana trendin yönünü belirler.
    Basitçe EMA50 kullanımıyla. Fiyat EMA50'nin üzerindeyse UP, altındaysa DOWN kabul edilir.
    """
    try:
        df = _ccxt_veri_getir(coin, timeframe='4h', limit=100)
        if df is None or df.empty:
            return "NÖTR"
        
        # 50 periyotluk üstel hareketli ortalama (EMA)
        ema50 = ta.ema(df['close'], length=50)
        if ema50 is None:
            return "NÖTR"
        
        son_kapanis = df['close'].iloc[-1]
        son_ema50 = ema50.iloc[-1]
        
        if son_kapanis > son_ema50:
            return "UP"
        elif son_kapanis < son_ema50:
            return "DOWN"
        else:
            return "NÖTR"
            
    except Exception:
        return "NÖTR"

# ============================================================
# 🛡️ FİLTRE 1: BTC KORELASYON KALKANI
# Altcoin piyasası BTC'ye %85+ korelasyonla bağlıdır.
# BTC düşüyorsa altcoin LONG açma, BTC yükseliyorsa SHORT açma.
# ============================================================
_BTC_KALKAN_CACHE = {'yon': 'NÖTR', 'son_guncelleme': 0}

def btc_kalkan_kontrol():
    """
    BTC'nin son 1 saatlik trendini kontrol eder.
    Dönüş: 'UP', 'DOWN' veya 'NÖTR'
    Cache: 5 dakika (aynı döngüde tekrar API çağrısı yapmaz)
    """
    import time as _t
    simdi = _t.time()
    
    # 5 dakika cache (her coin için tekrar çağırmayı önle)
    if simdi - _BTC_KALKAN_CACHE['son_guncelleme'] < 300:
        return _BTC_KALKAN_CACHE['yon']
    
    try:
        df = _ccxt_veri_getir('BTC/USDT', timeframe='1h', limit=20)
        if df is None or df.empty:
            return "NÖTR"
        
        # EMA8 ve EMA21 ile kısa vadeli BTC trend yönü
        ema8 = ta.ema(df['close'], length=8)
        ema21 = ta.ema(df['close'], length=21)
        
        if ema8 is None or ema21 is None:
            return "NÖTR"
        
        son_ema8 = ema8.iloc[-1]
        son_ema21 = ema21.iloc[-1]
        son_kapanis = df['close'].iloc[-1]
        
        # Son 3 mumun yönünü de kontrol et (momentum)
        son_3_degisim = (df['close'].iloc[-1] - df['close'].iloc[-3]) / df['close'].iloc[-3] * 100
        
        if son_ema8 > son_ema21 and son_kapanis > son_ema8 and son_3_degisim > 0:
            yon = "UP"
        elif son_ema8 < son_ema21 and son_kapanis < son_ema8 and son_3_degisim < 0:
            yon = "DOWN"
        else:
            yon = "NÖTR"
        
        _BTC_KALKAN_CACHE['yon'] = yon
        _BTC_KALKAN_CACHE['son_guncelleme'] = simdi
        return yon
        
    except Exception:
        return "NÖTR"

# ============================================================
# 🛡️ FİLTRE 2: 1 SAATLİK ORTA VADELİ TREND HIZALAMASI
# 15m sinyal + 1h trend + 4h trend = hepsi aynı yön olmalı
# ============================================================
def orta_trend_getir(coin):
    """
    1 Saatlik (1h) grafikte orta vadeli trendin yönünü belirler.
    EMA20 kullanılır. Fiyat EMA20'nin üzerindeyse UP, altındaysa DOWN.
    """
    try:
        df = _ccxt_veri_getir(coin, timeframe='1h', limit=50)
        if df is None or df.empty:
            return "NÖTR"
        
        ema20 = ta.ema(df['close'], length=20)
        if ema20 is None:
            return "NÖTR"
        
        son_kapanis = df['close'].iloc[-1]
        son_ema20 = ema20.iloc[-1]
        
        # EMA20'nin eğimi de kontrol et (yataysa NÖTR)
        ema_slope = (ema20.iloc[-1] - ema20.iloc[-3]) / ema20.iloc[-3] * 100 if len(ema20) > 3 else 0
        
        if son_kapanis > son_ema20 and ema_slope > 0.05:
            return "UP"
        elif son_kapanis < son_ema20 and ema_slope < -0.05:
            return "DOWN"
        else:
            return "NÖTR"
            
    except Exception:
        return "NÖTR"

# ============================================================
# 🛡️ FİLTRE 3: GİRİŞ ZAMANLAMASI (EMA MESAFE KONTROLÜ)
# Fiyat EMA20'den çok uzaklaşmışsa → treni kaçırmışsın, girme!
# ============================================================
def ema_mesafe_kontrol(df, yon, atr):
    """
    Fiyatın EMA20'ye olan mesafesini kontrol eder.
    ATR x 1.5'ten fazla uzaklaşmışsa → giriş yapmak riskli.
    Dönüş: True = giriş uygun, False = çok uzak, girme
    """
    try:
        ema20 = ta.ema(df['Hedef_Close'], length=20)
        if ema20 is None:
            return True  # Hesaplanamıyorsa engelleme
        
        son_fiyat = df['Hedef_Close'].iloc[-1]
        son_ema20 = ema20.iloc[-1]
        mesafe = abs(son_fiyat - son_ema20)
        max_mesafe = atr * 1.5  # ATR'nin 1.5 katından fazla uzaksa tehlike
        
        if "YÜKSELİŞ" in yon and son_fiyat > son_ema20 + max_mesafe:
            return False  # LONG için: fiyat çok yukarıda, tepeyi kovalama
        elif "DÜŞÜŞ" in yon and son_fiyat < son_ema20 - max_mesafe:
            return False  # SHORT için: fiyat çok aşağıda, dibi kovalama
        
        return True  # Mesafe uygun, giriş yapılabilir
        
    except Exception:
        return True  # Hata durumunda engelleme
