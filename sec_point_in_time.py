"""Point-in-time SEC CompanyFacts fundamentals for Factor v3.1 research."""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

import numpy as np
import pandas as pd
import requests


SEC_DATA_BASE = "https://data.sec.gov"
SEC_WWW_BASE = "https://www.sec.gov"
ALLOWED_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
ANNUAL_FORMS = {"10-K", "10-K/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}


CONCEPTS = {
    "revenue": (
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "Revenues"),
        ("us-gaap", "SalesRevenueNet"),
        ("us-gaap", "SalesRevenueGoodsNet"),
        ("us-gaap", "SalesRevenueServicesNet"),
    ),
    "net_income": (
        ("us-gaap", "NetIncomeLoss"),
        ("us-gaap", "ProfitLoss"),
        ("us-gaap", "NetIncomeLossAvailableToCommonStockholdersBasic"),
    ),
    "gross_profit": (("us-gaap", "GrossProfit"),),
    "operating_cash_flow": (
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    ),
    "capex": (
        ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
        ("us-gaap", "PaymentsForPropertyPlantAndEquipment"),
        ("us-gaap", "PaymentsToAcquireProductiveAssets"),
    ),
    "dividends": (
        ("us-gaap", "PaymentsOfDividends"),
        ("us-gaap", "PaymentsOfDividendsCommonStock"),
        ("us-gaap", "PaymentsOfOrdinaryDividends"),
    ),
    "assets": (("us-gaap", "Assets"),),
    "equity": (
        ("us-gaap", "StockholdersEquity"),
        ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        ("us-gaap", "PartnersCapital"),
    ),
    "debt_current": (
        ("us-gaap", "LongTermDebtAndFinanceLeaseObligationsCurrent"),
        ("us-gaap", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
        ("us-gaap", "LongTermDebtCurrent"),
        ("us-gaap", "DebtCurrent"),
    ),
    "debt_noncurrent": (
        ("us-gaap", "LongTermDebtAndFinanceLeaseObligationsNoncurrent"),
        ("us-gaap", "LongTermDebtAndCapitalLeaseObligationsNoncurrent"),
        ("us-gaap", "LongTermDebtNoncurrent"),
    ),
    "debt_total": (
        ("us-gaap", "LongTermDebtAndFinanceLeaseObligations"),
        ("us-gaap", "LongTermDebtAndCapitalLeaseObligations"),
        ("us-gaap", "LongTermDebt"),
    ),
    "shares": (
        ("dei", "EntityCommonStockSharesOutstanding"),
        ("us-gaap", "CommonStockSharesOutstanding"),
        ("us-gaap", "CommonStockSharesIssued"),
    ),
}

COMPACT_TAGS = {
    taxonomy: {tag for concepts in CONCEPTS.values() for item_taxonomy, tag in concepts if item_taxonomy == taxonomy}
    for taxonomy in {taxonomy for concepts in CONCEPTS.values() for taxonomy, _ in concepts}
}


@dataclass(frozen=True)
class SelectedFact:
    value: float
    start: Optional[pd.Timestamp]
    end: pd.Timestamp
    filed: pd.Timestamp
    form: str
    accession: str
    taxonomy: str
    tag: str
    unit: str


class IndexedCompanyFacts:
    """Pre-parsed CompanyFacts rows reused across historical signal dates."""

    def __init__(self, payload: Mapping):
        self.cik = payload.get("cik")
        self.entity_name = payload.get("entityName")
        self.rows: dict[tuple[str, str, str], list[SelectedFact]] = {}
        source_facts = payload.get("facts") or {}
        for taxonomy, tags in source_facts.items():
            for tag, concept in (tags or {}).items():
                for unit, unit_rows in ((concept or {}).get("units") or {}).items():
                    parsed_rows = []
                    for row in unit_rows:
                        form = str(row.get("form", ""))
                        if form not in ALLOWED_FORMS:
                            continue
                        start = _timestamp(row.get("start"))
                        end = _timestamp(row.get("end"))
                        filed = _timestamp(row.get("filed"))
                        try:
                            value = float(row.get("val"))
                        except (TypeError, ValueError):
                            continue
                        if end is None or filed is None or not np.isfinite(value):
                            continue
                        parsed_rows.append(
                            SelectedFact(
                                value=value,
                                start=start,
                                end=end,
                                filed=filed,
                                form=form,
                                accession=str(row.get("accn", "")),
                                taxonomy=taxonomy,
                                tag=tag,
                                unit=unit,
                            )
                        )
                    if parsed_rows:
                        self.rows[(taxonomy, tag, unit)] = parsed_rows

    def query(
        self,
        taxonomy: str,
        tag: str,
        units: Iterable[str],
        as_of: pd.Timestamp,
        filing_lag_days: int,
    ) -> list[SelectedFact]:
        as_of_date = pd.Timestamp(as_of).normalize()
        available_cutoff = as_of_date - pd.Timedelta(days=filing_lag_days)
        return [
            fact
            for unit in units
            for fact in self.rows.get((taxonomy, tag, unit), ())
            if fact.end <= as_of_date and fact.filed <= available_cutoff
        ]


def _env_value(name: str, env_file: str | Path = ".env") -> Optional[str]:
    direct = os.getenv(name)
    if direct:
        return direct.strip().strip('"').strip("'")
    project_dir = Path(__file__).resolve().parent
    requested = Path(env_file)
    candidates = [requested]
    if not requested.is_absolute():
        candidates.append(project_dir / requested)
    candidates.append(project_dir / "QuantBot" / ".env")
    seen = set()
    for path in candidates:
        resolved = str(path.resolve())
        if resolved in seen or not path.exists():
            continue
        seen.add(resolved)
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'") or None
    return None


def validate_user_agent(user_agent: Optional[str]) -> str:
    value = (user_agent or "").strip()
    if len(value) < 8 or "@" not in value or " " not in value:
        raise ValueError(
            "SEC_USER_AGENT sirket/proje adi ve iletisim e-postasi icermeli; "
            "ornek: StockPredictionPro adiniz@example.com"
        )
    return value


def compact_company_facts(payload: Mapping) -> dict:
    """Keep only concepts required by the factor model."""
    compact = {
        "cik": payload.get("cik"),
        "entityName": payload.get("entityName"),
        "facts": {},
    }
    source_facts = payload.get("facts") or {}
    for taxonomy, tags in COMPACT_TAGS.items():
        taxonomy_data = source_facts.get(taxonomy) or {}
        selected = {tag: taxonomy_data[tag] for tag in tags if tag in taxonomy_data}
        if selected:
            compact["facts"][taxonomy] = selected
    return compact


class SECCompanyFactsClient:
    def __init__(
        self,
        user_agent: str,
        cache_dir: str | Path = ".cache/sec_companyfacts",
        requests_per_second: float = 4.0,
        timeout: float = 30.0,
        offline_cache: bool = False,
    ):
        self.user_agent = validate_user_agent(user_agent)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.requests_per_second = min(9.0, max(0.5, float(requests_per_second)))
        self.timeout = timeout
        self.offline_cache = bool(offline_cache)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json",
            }
        )
        self._last_request = 0.0
        self._rate_lock = threading.Lock()
        self._memory_facts: dict[str, dict] = {}
        self._ticker_map: Optional[dict[str, str]] = None

    @classmethod
    def from_env(cls, env_file: str | Path = ".env", **kwargs):
        return cls(validate_user_agent(_env_value("SEC_USER_AGENT", env_file)), **kwargs)

    def _wait_for_rate_limit(self) -> None:
        minimum_interval = 1.0 / self.requests_per_second
        with self._rate_lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < minimum_interval:
                time.sleep(minimum_interval - elapsed)
            self._last_request = time.monotonic()

    def _request_json(self, url: str) -> dict:
        last_error: Optional[Exception] = None
        for attempt in range(4):
            self._wait_for_rate_limit()
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"SEC gecici HTTP {response.status_code}")
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("SEC JSON kok nesnesi gecersiz")
                return data
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(1.5 * (2 ** attempt))
        raise RuntimeError(f"SEC verisi alinamadi: {last_error}") from last_error

    @staticmethod
    def _cache_fresh(path: Path, max_age_hours: float) -> bool:
        if not path.exists():
            return False
        age = time.time() - path.stat().st_mtime
        return age <= max_age_hours * 3600

    @staticmethod
    def _read_gzip_json(path: Path) -> dict:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_gzip_json(path: Path, payload: Mapping) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as handle:
            json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
        os.replace(temporary, path)

    def ticker_map(self, max_age_hours: float = 168.0) -> dict[str, str]:
        if self._ticker_map is not None:
            return dict(self._ticker_map)
        cache_file = self.cache_dir / "company_tickers.json.gz"
        if cache_file.exists() and (self.offline_cache or self._cache_fresh(cache_file, max_age_hours)):
            payload = self._read_gzip_json(cache_file)
        elif self.offline_cache:
            raise RuntimeError(f'Cevirimdisi SEC ticker onbellegi eksik: {cache_file}')
        else:
            payload = self._request_json(f"{SEC_WWW_BASE}/files/company_tickers.json")
            self._write_gzip_json(cache_file, payload)

        result = {}
        for row in payload.values():
            ticker = str(row.get("ticker", "")).upper().strip()
            cik = row.get("cik_str")
            if ticker and cik is not None:
                result[ticker] = str(int(cik)).zfill(10)
        self._ticker_map = result
        return dict(result)

    def cik_for_ticker(self, ticker: str) -> Optional[str]:
        if self._ticker_map is None:
            self.ticker_map()
        return self._ticker_map.get(ticker.upper().strip())

    def company_facts(self, cik: str, max_age_hours: float = 24.0) -> dict:
        normalized_cik = str(int(cik)).zfill(10)
        if normalized_cik in self._memory_facts:
            return self._memory_facts[normalized_cik]
        cache_file = self.cache_dir / f"CIK{normalized_cik}.json.gz"
        if cache_file.exists() and (self.offline_cache or self._cache_fresh(cache_file, max_age_hours)):
            compact = self._read_gzip_json(cache_file)
        elif self.offline_cache:
            raise RuntimeError(f'Cevirimdisi SEC sirket onbellegi eksik: {cache_file}')
        else:
            payload = self._request_json(
                f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{normalized_cik}.json"
            )
            compact = compact_company_facts(payload)
            self._write_gzip_json(cache_file, compact)
        self._memory_facts[normalized_cik] = compact
        return compact


def _timestamp(value) -> Optional[pd.Timestamp]:
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    timestamp = pd.Timestamp(parsed)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize()


def _fact_rows(
    payload: Mapping | IndexedCompanyFacts,
    taxonomy: str,
    tag: str,
    units: Iterable[str],
    as_of: pd.Timestamp,
    filing_lag_days: int,
) -> list[SelectedFact]:
    if isinstance(payload, IndexedCompanyFacts):
        return payload.query(taxonomy, tag, units, as_of, filing_lag_days)
    concept = (((payload.get("facts") or {}).get(taxonomy) or {}).get(tag) or {})
    unit_map = concept.get("units") or {}
    available_cutoff = pd.Timestamp(as_of).normalize() - pd.Timedelta(days=filing_lag_days)
    result = []
    for unit in units:
        for row in unit_map.get(unit, []):
            form = str(row.get("form", ""))
            if form not in ALLOWED_FORMS:
                continue
            start = _timestamp(row.get("start"))
            end = _timestamp(row.get("end"))
            filed = _timestamp(row.get("filed"))
            try:
                value = float(row.get("val"))
            except (TypeError, ValueError):
                continue
            if (
                end is None or filed is None or end > pd.Timestamp(as_of).normalize()
                or filed > available_cutoff or not np.isfinite(value)
            ):
                continue
            result.append(
                SelectedFact(
                    value=value,
                    start=start,
                    end=end,
                    filed=filed,
                    form=form,
                    accession=str(row.get("accn", "")),
                    taxonomy=taxonomy,
                    tag=tag,
                    unit=unit,
                )
            )
    return result


def _duration_days(fact: SelectedFact) -> Optional[int]:
    if fact.start is None:
        return None
    return int((fact.end - fact.start).days)


def latest_instant(
    payload: Mapping,
    concept_name: str,
    as_of,
    units: Iterable[str] = ("USD",),
    filing_lag_days: int = 1,
) -> Optional[SelectedFact]:
    as_of_date = pd.Timestamp(as_of).normalize()
    candidates = []
    for priority, (taxonomy, tag) in enumerate(CONCEPTS[concept_name]):
        for fact in _fact_rows(payload, taxonomy, tag, units, as_of_date, filing_lag_days):
            if fact.start is None:
                candidates.append((fact.end, fact.filed, -priority, fact.accession, fact))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[:4])[-1]


def _deduplicate_periods(facts: list[SelectedFact]) -> list[SelectedFact]:
    selected: dict[tuple, SelectedFact] = {}
    for fact in facts:
        key = (fact.start, fact.end, fact.form.startswith("10-K"))
        previous = selected.get(key)
        if previous is None or (fact.filed, fact.accession) > (previous.filed, previous.accession):
            selected[key] = fact
    return list(selected.values())


def _ttm_for_tag(
    payload: Mapping,
    taxonomy: str,
    tag: str,
    as_of: pd.Timestamp,
    filing_lag_days: int,
) -> Optional[SelectedFact]:
    facts = _fact_rows(payload, taxonomy, tag, ("USD",), as_of, filing_lag_days)
    durations = [fact for fact in facts if fact.start is not None]
    durations = _deduplicate_periods(durations)
    annuals = [
        fact for fact in durations
        if fact.form in ANNUAL_FORMS and 300 <= (_duration_days(fact) or 0) <= 400
    ]
    quarters = [
        fact for fact in durations
        if fact.form in QUARTERLY_FORMS and 60 <= (_duration_days(fact) or 0) <= 300
    ]
    annual = max(annuals, key=lambda fact: (fact.end, fact.filed), default=None)
    if not quarters:
        return annual

    latest_quarter_end = max(fact.end for fact in quarters)
    latest_end_facts = [fact for fact in quarters if fact.end == latest_quarter_end]
    latest_filing = max(fact.filed for fact in latest_end_facts)
    current_candidates = [fact for fact in latest_end_facts if fact.filed == latest_filing]
    current_ytd = max(current_candidates, key=lambda fact: _duration_days(fact) or 0)

    if annual is None:
        return None
    if annual.end >= current_ytd.end:
        return annual

    target_prior_end = current_ytd.end - pd.DateOffset(years=1)
    current_duration = _duration_days(current_ytd) or 0
    prior_candidates = []
    for fact in quarters:
        duration = _duration_days(fact) or 0
        end_gap = abs((fact.end - target_prior_end).days)
        if fact.end < current_ytd.end and end_gap <= 45 and abs(duration - current_duration) <= 25:
            prior_candidates.append(fact)
    if not prior_candidates:
        return annual

    prior_ytd = max(prior_candidates, key=lambda fact: (fact.filed, fact.accession))
    return SelectedFact(
        value=float(annual.value + current_ytd.value - prior_ytd.value),
        start=annual.start,
        end=current_ytd.end,
        filed=max(annual.filed, current_ytd.filed, prior_ytd.filed),
        form="TTM",
        accession=current_ytd.accession,
        taxonomy=taxonomy,
        tag=tag,
        unit="USD",
    )


def ttm_fact(
    payload: Mapping,
    concept_name: str,
    as_of,
    filing_lag_days: int = 1,
) -> Optional[SelectedFact]:
    as_of_date = pd.Timestamp(as_of).normalize()
    candidates = []
    for priority, (taxonomy, tag) in enumerate(CONCEPTS[concept_name]):
        fact = _ttm_for_tag(payload, taxonomy, tag, as_of_date, filing_lag_days)
        if fact is not None:
            candidates.append((fact.end, fact.filed, -priority, fact.accession, fact))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[:4])[-1]


def _safe_ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or not np.isfinite(denominator) or denominator == 0:
        return None
    value = numerator / denominator
    return float(value) if np.isfinite(value) else None


def _growth(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or abs(previous) < 1e-9:
        return None
    value = (current - previous) / abs(previous)
    return float(value) if np.isfinite(value) else None


def build_factor_snapshot(
    payload: Mapping,
    as_of,
    raw_close: float,
    filing_lag_days: int = 1,
) -> dict:
    """Build only metrics knowable by the signal date."""
    as_of_date = pd.Timestamp(as_of).normalize()
    prior_as_of = as_of_date - pd.DateOffset(years=1)

    revenue = ttm_fact(payload, "revenue", as_of_date, filing_lag_days)
    net_income = ttm_fact(payload, "net_income", as_of_date, filing_lag_days)
    gross_profit = ttm_fact(payload, "gross_profit", as_of_date, filing_lag_days)
    operating_cash = ttm_fact(payload, "operating_cash_flow", as_of_date, filing_lag_days)
    capex = ttm_fact(payload, "capex", as_of_date, filing_lag_days)
    dividends = ttm_fact(payload, "dividends", as_of_date, filing_lag_days)
    prior_revenue = ttm_fact(payload, "revenue", prior_as_of, filing_lag_days)
    prior_net_income = ttm_fact(payload, "net_income", prior_as_of, filing_lag_days)
    assets = latest_instant(payload, "assets", as_of_date, filing_lag_days=filing_lag_days)
    equity = latest_instant(payload, "equity", as_of_date, filing_lag_days=filing_lag_days)
    debt_current = latest_instant(payload, "debt_current", as_of_date, filing_lag_days=filing_lag_days)
    debt_noncurrent = latest_instant(payload, "debt_noncurrent", as_of_date, filing_lag_days=filing_lag_days)
    debt_total = latest_instant(payload, "debt_total", as_of_date, filing_lag_days=filing_lag_days)
    shares = latest_instant(
        payload,
        "shares",
        as_of_date,
        units=("shares",),
        filing_lag_days=filing_lag_days,
    )

    market_cap = None
    if shares is not None and raw_close is not None and raw_close > 0:
        market_cap = float(shares.value * raw_close)
    debt_value = None
    if debt_current is not None or debt_noncurrent is not None:
        debt_value = (debt_current.value if debt_current else 0.0) + (
            debt_noncurrent.value if debt_noncurrent else 0.0
        )
    elif debt_total is not None:
        debt_value = debt_total.value

    revenue_value = revenue.value if revenue else None
    net_income_value = net_income.value if net_income else None
    gross_profit_value = gross_profit.value if gross_profit else None
    operating_cash_value = operating_cash.value if operating_cash else None
    capex_value = abs(capex.value) if capex else None
    dividends_value = abs(dividends.value) if dividends else None
    free_cash_flow = (
        operating_cash_value - capex_value
        if operating_cash_value is not None and capex_value is not None else None
    )

    snapshot = {
        "roe": _safe_ratio(net_income_value, equity.value if equity else None),
        "roa": _safe_ratio(net_income_value, assets.value if assets else None),
        "profit_margin": _safe_ratio(net_income_value, revenue_value),
        "gross_margin": _safe_ratio(gross_profit_value, revenue_value),
        "revenue_growth": _growth(
            revenue_value,
            prior_revenue.value if prior_revenue else None,
        ),
        "earnings_growth": _growth(
            net_income_value,
            prior_net_income.value if prior_net_income else None,
        ),
        "debt_to_equity": (
            _safe_ratio(debt_value, equity.value) * 100.0
            if debt_value is not None and equity is not None and equity.value != 0 else None
        ),
        "earnings_yield": _safe_ratio(net_income_value, market_cap),
        "fcf_yield": _safe_ratio(free_cash_flow, market_cap),
        "dividend_yield": _safe_ratio(dividends_value, market_cap),
        "sec_market_cap": market_cap,
        "sec_shares_outstanding": shares.value if shares else None,
        "sec_fundamental_as_of": as_of_date.date().isoformat(),
        "sec_latest_filing": max(
            (fact.filed for fact in (revenue, net_income, assets, equity) if fact is not None),
            default=None,
        ),
    }
    snapshot["sec_latest_filing"] = (
        snapshot["sec_latest_filing"].date().isoformat()
        if snapshot["sec_latest_filing"] is not None else None
    )
    factor_keys = (
        "roe", "roa", "profit_margin", "gross_margin", "revenue_growth",
        "earnings_growth", "debt_to_equity", "earnings_yield", "fcf_yield",
        "dividend_yield",
    )
    snapshot["sec_metric_count"] = sum(snapshot[key] is not None for key in factor_keys)
    snapshot["sec_data_status"] = "OK" if snapshot["sec_metric_count"] >= 6 else "PARTIAL"
    snapshot.update(
        {
            "pe_orani": (1.0 / snapshot["earnings_yield"] if snapshot["earnings_yield"] and snapshot["earnings_yield"] > 0 else None),
            "borc_ozkaynak": snapshot["debt_to_equity"],
            "fcf_getiri": (snapshot["fcf_yield"] * 100.0 if snapshot["fcf_yield"] is not None else None),
            "gelir_buyume": (snapshot["revenue_growth"] * 100.0 if snapshot["revenue_growth"] is not None else None),
            "temettu_verimi": (snapshot["dividend_yield"] * 100.0 if snapshot["dividend_yield"] is not None else None),
        }
    )
    return snapshot


class SECPointInTimeProvider:
    def __init__(
        self,
        client: SECCompanyFactsClient,
        histories: Mapping[str, pd.DataFrame],
        filing_lag_days: int = 1,
        progress: bool = False,
    ):
        self.client = client
        self.histories = histories
        self.filing_lag_days = max(1, int(filing_lag_days))
        self.progress = progress
        self.last_diagnostics: dict = {}
        self._fact_indexes: dict[str, IndexedCompanyFacts] = {}
        self._snapshot_cache: dict[tuple[str, str], dict] = {}

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "provider": "SECCompanyFacts",
            "source": "https://data.sec.gov/api/xbrl/companyfacts/",
            "filing_lag_days": self.filing_lag_days,
            "same_day_filings_excluded": True,
            "point_in_time_eligible": True,
        }

    @staticmethod
    def _raw_close(history: pd.DataFrame, as_of: pd.Timestamp) -> Optional[float]:
        from stock_walkforward import normalize_history

        frame = normalize_history(history)
        available = frame.loc[frame.index <= pd.Timestamp(as_of).normalize()]
        if available.empty:
            return None
        column = "RawClose" if "RawClose" in available.columns else "Close"
        value = available[column].iloc[-1]
        return float(value) if pd.notna(value) and np.isfinite(float(value)) and float(value) > 0 else None

    def __call__(self, signal_date: pd.Timestamp, symbols: list[str]) -> dict[str, dict]:
        snapshots = {}
        errors = {}
        missing_cik = []
        for symbol in symbols:
            cache_key = (symbol, pd.Timestamp(signal_date).date().isoformat())
            if cache_key in self._snapshot_cache:
                snapshots[symbol] = dict(self._snapshot_cache[cache_key])
                continue
            cik = self.client.cik_for_ticker(symbol)
            if cik is None:
                missing_cik.append(symbol)
                continue
            raw_close = self._raw_close(self.histories.get(symbol, pd.DataFrame()), signal_date)
            if raw_close is None:
                errors[symbol] = "raw_close_missing"
                continue
            try:
                payload = self.client.company_facts(cik)
                if cik not in self._fact_indexes:
                    self._fact_indexes[cik] = IndexedCompanyFacts(payload)
                    if self.progress and len(self._fact_indexes) % 10 == 0:
                        print(
                            f"  SEC indeksleri hazirlaniyor: {len(self._fact_indexes)} sirket",
                            flush=True,
                        )
                snapshot = build_factor_snapshot(
                    self._fact_indexes[cik],
                    signal_date,
                    raw_close,
                    filing_lag_days=self.filing_lag_days,
                )
                snapshot["sec_cik"] = cik
                snapshots[symbol] = snapshot
                self._snapshot_cache[cache_key] = dict(snapshot)
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}: {str(exc)[:120]}"
        self.last_diagnostics = {
            "signal_date": pd.Timestamp(signal_date).date().isoformat(),
            "requested": len(symbols),
            "returned": len(snapshots),
            "missing_cik": missing_cik,
            "errors": errors,
        }
        return snapshots


def coverage_report(snapshots: Mapping[str, Mapping]) -> dict:
    counts = [int(snapshot.get("sec_metric_count", 0)) for snapshot in snapshots.values()]
    return {
        "symbols": len(snapshots),
        "ok": sum(snapshot.get("sec_data_status") == "OK" for snapshot in snapshots.values()),
        "partial": sum(snapshot.get("sec_data_status") != "OK" for snapshot in snapshots.values()),
        "average_metric_count": float(np.mean(counts)) if counts else 0.0,
        "minimum_metric_count": min(counts) if counts else 0,
        "maximum_metric_count": max(counts) if counts else 0,
    }
