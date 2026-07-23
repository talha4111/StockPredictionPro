"""Forward-return tracking for the stock research engine."""

import os
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf


HORIZONS = (5, 20, 60, 120)
OUTCOME_TABLE = 'hisse_sinyal_sonuclari'

YFINANCE_CACHE_DIR = os.getenv(
    'YFINANCE_CACHE_DIR',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache', 'yfinance'),
)
try:
    os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)
    yf.set_tz_cache_location(YFINANCE_CACHE_DIR)
except OSError:
    pass


OUTCOME_COLUMNS = {
    'entry_date': 'TEXT',
    'entry_price': 'REAL',
    'benchmark_symbol': 'TEXT',
    'sector_benchmark_symbol': 'TEXT',
    'mfe_20g': 'REAL',
    'mae_20g': 'REAL',
    'mfe_60g': 'REAL',
    'mae_60g': 'REAL',
    'updated_at': 'TEXT',
}
for _horizon in HORIZONS:
    OUTCOME_COLUMNS.update({
        f'fiyat_{_horizon}g': 'REAL',
        f'getiri_{_horizon}g': 'REAL',
        f'spy_getiri_{_horizon}g': 'REAL',
        f'sektor_getiri_{_horizon}g': 'REAL',
        f'excess_{_horizon}g': 'REAL',
        f'excess_spy_{_horizon}g': 'REAL',
        f'excess_sektor_{_horizon}g': 'REAL',
        f'sonuc_{_horizon}g_tarih': 'TEXT',
    })


def sonuc_semasini_hazirla(conn):
    column_sql = ',\n            '.join(
        f'{column} {column_type}' for column, column_type in OUTCOME_COLUMNS.items()
    )
    conn.execute(f'''CREATE TABLE IF NOT EXISTS {OUTCOME_TABLE} (
            signal_id INTEGER PRIMARY KEY,
            {column_sql},
            FOREIGN KEY(signal_id) REFERENCES hisse_sinyalleri(id)
        )''')

    existing = {
        row[1] for row in conn.execute(f'PRAGMA table_info({OUTCOME_TABLE})')
    }
    for column, column_type in OUTCOME_COLUMNS.items():
        if column not in existing:
            conn.execute(
                f'ALTER TABLE {OUTCOME_TABLE} ADD COLUMN {column} {column_type}'
            )
    conn.commit()


def _table_columns(conn, table_name):
    return {row[1] for row in conn.execute(f'PRAGMA table_info({table_name})')}


def _parse_date(value):
    if value is None:
        return None
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def _aware_now(now=None):
    current = now or datetime.now(timezone.utc)
    if isinstance(current, date) and not isinstance(current, datetime):
        current = datetime.combine(current, datetime.min.time(), tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current


def tamamlanmamis_gunluk_mumu_cikar(df, now=None):
    """Drop the current US session bar until 16:15 New York time."""
    if df is None or df.empty:
        return df
    current_ny = _aware_now(now).astimezone(ZoneInfo('America/New_York'))
    last_date = pd.Timestamp(df.index[-1]).date()
    close_settled = (current_ny.hour, current_ny.minute) >= (16, 15)
    if last_date == current_ny.date() and not close_settled:
        return df.iloc[:-1].copy()
    return df


def _normalize_history(df, now=None):
    if df is None or df.empty or 'Close' not in df.columns:
        return pd.DataFrame()

    frame = tamamlanmamis_gunluk_mumu_cikar(df.copy(), now=now)
    if frame.empty:
        return frame
    frame = frame.sort_index()
    frame.index = pd.Index(
        [pd.Timestamp(value).date() for value in frame.index], name='date'
    )
    frame = frame[~frame.index.duplicated(keep='last')]
    frame['Close'] = pd.to_numeric(frame['Close'], errors='coerce')
    if 'High' not in frame.columns:
        frame['High'] = frame['Close']
    if 'Low' not in frame.columns:
        frame['Low'] = frame['Close']
    frame['High'] = pd.to_numeric(frame['High'], errors='coerce')
    frame['Low'] = pd.to_numeric(frame['Low'], errors='coerce')
    return frame.dropna(subset=['Close'])


def _default_price_loader(symbol, start_date, end_date):
    return yf.Ticker(symbol).history(
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        auto_adjust=True,
        actions=False,
    )


def _pending_signals(conn, max_signals=None):
    signal_columns = _table_columns(conn, 'hisse_sinyalleri')
    if not signal_columns:
        return []

    if 'as_of_date' in signal_columns:
        as_of_expr = "COALESCE(NULLIF(s.as_of_date, ''), substr(s.tarih, 1, 10))"
    else:
        as_of_expr = 'substr(s.tarih, 1, 10)'

    sql = f'''SELECT
            s.id, s.sembol, s.sektor, {as_of_expr} AS effective_date,
            s.fiyat
        FROM hisse_sinyalleri s
        LEFT JOIN {OUTCOME_TABLE} o ON o.signal_id = s.id
        WHERE {as_of_expr} IS NOT NULL
          AND (o.signal_id IS NULL OR o.getiri_120g IS NULL)
        ORDER BY effective_date, s.id'''
    params = []
    if max_signals is not None:
        sql += ' LIMIT ?'
        params.append(int(max_signals))

    return [
        {
            'id': row[0],
            'symbol': row[1],
            'sector': row[2],
            'as_of_date': _parse_date(row[3]),
            'recorded_price': row[4],
        }
        for row in conn.execute(sql, params).fetchall()
        if _parse_date(row[3]) is not None
    ]


def _price_on_or_before(frame, target_date, column='Close'):
    if frame is None or frame.empty:
        return None, None
    eligible = frame.loc[frame.index <= target_date]
    if eligible.empty:
        return None, None
    value = eligible[column].iloc[-1]
    if pd.isna(value) or not np.isfinite(float(value)):
        return None, None
    return eligible.index[-1], float(value)


def _benchmark_return(frame, entry_date, target_date):
    _, entry_price = _price_on_or_before(frame, entry_date)
    _, target_price = _price_on_or_before(frame, target_date)
    if entry_price is None or target_price is None or entry_price <= 0:
        return None
    return float(target_price / entry_price - 1.0)


def _signal_outcome(signal, stock_frame, spy_frame, sector_frame, sector_symbol, now=None):
    requested_entry_date = signal['as_of_date']
    entry_date, entry_price = _price_on_or_before(stock_frame, requested_entry_date)
    if entry_date is None or entry_price is None or entry_price <= 0:
        return None
    if (requested_entry_date - entry_date).days > 4:
        return None

    future = stock_frame.loc[stock_frame.index > entry_date]
    result = {
        'signal_id': signal['id'],
        'entry_date': entry_date.isoformat(),
        'entry_price': entry_price,
        'benchmark_symbol': 'SPY',
        'sector_benchmark_symbol': sector_symbol,
        'updated_at': _aware_now(now).isoformat(timespec='seconds'),
    }

    for horizon in HORIZONS:
        if len(future) < horizon:
            continue
        target_row = future.iloc[horizon - 1]
        target_date = future.index[horizon - 1]
        target_price = float(target_row['Close'])
        stock_return = target_price / entry_price - 1.0
        spy_return = _benchmark_return(spy_frame, entry_date, target_date)
        sector_return = _benchmark_return(sector_frame, entry_date, target_date)
        excess_spy = stock_return - spy_return if spy_return is not None else None
        excess_sector = (
            stock_return - sector_return if sector_return is not None else None
        )

        result.update({
            f'fiyat_{horizon}g': target_price,
            f'getiri_{horizon}g': stock_return,
            f'spy_getiri_{horizon}g': spy_return,
            f'sektor_getiri_{horizon}g': sector_return,
            f'excess_{horizon}g': excess_spy,
            f'excess_spy_{horizon}g': excess_spy,
            f'excess_sektor_{horizon}g': excess_sector,
            f'sonuc_{horizon}g_tarih': target_date.isoformat(),
        })

    for horizon in (20, 60):
        if len(future) < horizon:
            continue
        window = future.iloc[:horizon]
        result[f'mfe_{horizon}g'] = float(window['High'].max() / entry_price - 1.0)
        result[f'mae_{horizon}g'] = float(window['Low'].min() / entry_price - 1.0)
    return result


def _upsert_outcome(conn, outcome):
    columns = ['signal_id'] + list(OUTCOME_COLUMNS)
    values = [outcome.get(column) for column in columns]
    placeholders = ', '.join('?' for _ in columns)
    update_sql = ', '.join(
        f'{column}=COALESCE(excluded.{column}, {OUTCOME_TABLE}.{column})'
        for column in columns
        if column != 'signal_id'
    )
    conn.execute(
        f'''INSERT INTO {OUTCOME_TABLE} ({', '.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(signal_id) DO UPDATE SET {update_sql}''',
        values,
    )


def sinyal_sonuclarini_guncelle(
    db_path,
    sector_etfs,
    price_loader: Optional[Callable] = None,
    now=None,
    max_signals=None,
):
    """Populate all currently mature forward horizons for stored signals."""
    summary = {
        'signals_found': 0,
        'signals_updated': 0,
        'symbols_loaded': 0,
        'horizons': {f'{horizon}g': 0 for horizon in HORIZONS},
        'errors': {},
    }
    if not os.path.exists(db_path):
        return summary

    loader = price_loader or _default_price_loader
    conn = sqlite3.connect(db_path)
    try:
        sonuc_semasini_hazirla(conn)
        signals = _pending_signals(conn, max_signals=max_signals)
        summary['signals_found'] = len(signals)
        if not signals:
            return summary

        earliest = min(signal['as_of_date'] for signal in signals) - timedelta(days=10)
        current = _aware_now(now)
        end_date = current.date() + timedelta(days=2)
        symbols = {signal['symbol'] for signal in signals}
        benchmark_symbols = {'SPY'} | {
            sector_etfs.get(signal['sector'])
            for signal in signals
            if sector_etfs.get(signal['sector'])
        }

        histories = {}
        for symbol in sorted(symbols | benchmark_symbols):
            try:
                history = loader(symbol, earliest, end_date)
                normalized = _normalize_history(history, now=current)
                if normalized.empty:
                    raise ValueError('empty price history')
                histories[symbol] = normalized
            except Exception as exc:
                summary['errors'][symbol] = f'{type(exc).__name__}: {str(exc)[:160]}'
        summary['symbols_loaded'] = len(histories)

        for signal in signals:
            stock_frame = histories.get(signal['symbol'])
            if stock_frame is None:
                continue
            sector_symbol = sector_etfs.get(signal['sector'])
            outcome = _signal_outcome(
                signal,
                stock_frame,
                histories.get('SPY'),
                histories.get(sector_symbol),
                sector_symbol,
                now=current,
            )
            if outcome is None:
                summary['errors'][f"signal:{signal['id']}"] = 'entry price not found'
                continue
            _upsert_outcome(conn, outcome)
            summary['signals_updated'] += 1
            for horizon in HORIZONS:
                if outcome.get(f'getiri_{horizon}g') is not None:
                    summary['horizons'][f'{horizon}g'] += 1
        conn.commit()
        return summary
    finally:
        conn.close()


def _horizon_metrics(frame, horizon):
    return_column = f'getiri_{horizon}g'
    excess_column = f'excess_spy_{horizon}g'
    sector_excess_column = f'excess_sektor_{horizon}g'
    valid_returns = frame.dropna(subset=[return_column])
    valid_excess = frame.dropna(subset=[excess_column])
    valid_sector_excess = frame.dropna(subset=[sector_excess_column])
    result = {
        'sample': int(len(valid_returns)),
        'benchmark_sample': int(len(valid_excess)),
        'sector_sample': int(len(valid_sector_excess)),
        'mean_return': None,
        'median_return': None,
        'mean_excess_spy': None,
        'median_excess_spy': None,
        'positive_excess_rate': None,
        'mean_excess_sector': None,
        'median_excess_sector': None,
        'positive_excess_sector_rate': None,
        'score_ic': None,
    }
    if not valid_returns.empty:
        result['mean_return'] = float(valid_returns[return_column].mean())
        result['median_return'] = float(valid_returns[return_column].median())
    if not valid_excess.empty:
        result['mean_excess_spy'] = float(valid_excess[excess_column].mean())
        result['median_excess_spy'] = float(valid_excess[excess_column].median())
        result['positive_excess_rate'] = float(
            (valid_excess[excess_column] > 0).mean()
        )
    if not valid_sector_excess.empty:
        result['mean_excess_sector'] = float(
            valid_sector_excess[sector_excess_column].mean()
        )
        result['median_excess_sector'] = float(
            valid_sector_excess[sector_excess_column].median()
        )
        result['positive_excess_sector_rate'] = float(
            (valid_sector_excess[sector_excess_column] > 0).mean()
        )

    ic_frame = valid_excess.dropna(subset=['score'])
    if len(ic_frame) >= 5 and ic_frame['score'].nunique() > 1:
        result['score_ic'] = float(
            ic_frame['score'].rank(method='average').corr(
                ic_frame[excess_column].rank(method='average')
            )
        )
    return result


def performans_ozeti(db_path, strategy_version=None):
    """Summarize deduplicated observations; duplicates remain untouched on disk."""
    empty = {
        'independent_signals': 0,
        'duplicates_excluded': 0,
        'horizons': {},
        'by_decision_20g': {},
    }
    if not os.path.exists(db_path):
        return empty

    conn = sqlite3.connect(db_path)
    try:
        sonuc_semasini_hazirla(conn)
        signal_columns = _table_columns(conn, 'hisse_sinyalleri')
        if not signal_columns:
            return empty

        date_expr = (
            "COALESCE(NULLIF(s.as_of_date, ''), substr(s.tarih, 1, 10))"
            if 'as_of_date' in signal_columns else 'substr(s.tarih, 1, 10)'
        )
        version_expr = (
            "COALESCE(NULLIF(s.strategy_version, ''), 'legacy-v2')"
            if 'strategy_version' in signal_columns else "'legacy-v2'"
        )
        decision_expr = (
            "COALESCE(NULLIF(s.decision, ''), 'LEGACY_SIGNAL')"
            if 'decision' in signal_columns else "'LEGACY_SIGNAL'"
        )
        setup_expr = (
            "COALESCE(NULLIF(s.setup, ''), 'LEGACY_COMBINED')"
            if 'setup' in signal_columns else "'LEGACY_COMBINED'"
        )

        horizon_select = ', '.join(
            f'o.getiri_{horizon}g, o.excess_spy_{horizon}g, '
            f'o.excess_sektor_{horizon}g'
            for horizon in HORIZONS
        )
        sql = f'''WITH independent AS (
                SELECT MAX(s.id) AS id
                FROM hisse_sinyalleri s
                GROUP BY s.sembol, {date_expr}, {version_expr}
            )
            SELECT s.id, s.sembol, {date_expr} AS effective_date,
                   {version_expr} AS strategy_version,
                   {decision_expr} AS decision,
                   {setup_expr} AS setup,
                   s.ai_skor AS score,
                   {horizon_select}
            FROM independent i
            JOIN hisse_sinyalleri s ON s.id = i.id
            JOIN {OUTCOME_TABLE} o ON o.signal_id = s.id'''
        params = []
        if strategy_version:
            sql += f' WHERE {version_expr} = ?'
            params.append(strategy_version)

        rows = conn.execute(sql, params).fetchall()
        columns = [
            'id', 'symbol', 'effective_date', 'strategy_version',
            'decision', 'setup', 'score',
        ]
        for horizon in HORIZONS:
            columns.extend([
                f'getiri_{horizon}g',
                f'excess_spy_{horizon}g',
                f'excess_sektor_{horizon}g',
            ])
        frame = pd.DataFrame(rows, columns=columns)
        if frame.empty:
            return empty

        outcome_mask = frame[
            [f'getiri_{horizon}g' for horizon in HORIZONS]
        ].notna().any(axis=1)
        frame = frame.loc[outcome_mask].copy()
        total_where = (
            '(' + ' OR '.join(
                f'o.getiri_{horizon}g IS NOT NULL' for horizon in HORIZONS
            ) + ')'
        )
        total_params = []
        if strategy_version:
            total_where += f' AND {version_expr} = ?'
            total_params.append(strategy_version)
        total_outcome_rows = conn.execute(
            f'''SELECT COUNT(*) FROM hisse_sinyalleri s
                JOIN {OUTCOME_TABLE} o ON o.signal_id = s.id
                WHERE {total_where}''',
            total_params,
        ).fetchone()[0]

        result = {
            'independent_signals': int(len(frame)),
            'duplicates_excluded': max(0, int(total_outcome_rows - len(frame))),
            'horizons': {
                f'{horizon}g': _horizon_metrics(frame, horizon)
                for horizon in HORIZONS
            },
            'by_decision_20g': {},
        }
        for decision, group in frame.groupby('decision'):
            metrics = _horizon_metrics(group, 20)
            if metrics['sample']:
                result['by_decision_20g'][decision] = metrics
        return result
    finally:
        conn.close()
