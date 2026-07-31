"""Provider field and unit normalization.

All normalized rows use:
- price/preclose: yuan
- volume: shares (Tushare/AKShare deliver lots of 100 shares)
- amount: yuan (Tushare daily delivers thousand yuan)
- turnover_rate/pct_change: percent, as reported by the provider
- Decimal values are constructed from the provider's string form and never
  transit through float storage.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

LOT_SIZE = Decimal("100")
THOUSAND = Decimal("1000")
WAN = Decimal("10000")


def as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "null", "--", "na"}:
        return None
    return text


def decimal_from(value: Any) -> Decimal | None:
    text = as_text(value)
    if text is None:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _required_decimal(value: Any, field: str) -> Decimal:
    parsed = decimal_from(value)
    if parsed is None:
        raise ValueError(f"missing or invalid decimal field: {field}")
    return parsed


def parse_date_yyyymmdd(value: Any) -> date | None:
    text = as_text(value)
    if text is None:
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def parse_date_dash(value: Any) -> date | None:
    text = as_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def clock_time(value: Any) -> time | None:
    text = as_text(value)
    if text is None:
        return None
    if ":" in text:
        try:
            return time.fromisoformat(text)
        except ValueError:
            return None
    digits = "".join(character for character in text if character.isdigit())
    if not digits:
        return None
    digits = digits.zfill(6)
    if len(digits) != 6 or digits == "000000":
        return None
    try:
        return time(int(digits[:2]), int(digits[2:4]), int(digits[4:]))
    except ValueError:
        return None


def normalize_tushare_daily(row: Mapping[str, Any]) -> dict[str, Any]:
    """Tushare ``daily`` row: vol in lots, amount in thousand yuan."""

    trade_date = parse_date_yyyymmdd(row.get("trade_date"))
    if trade_date is None:
        raise ValueError("tushare daily row has invalid trade_date")
    return {
        "code": row["ts_code"].split(".")[0].zfill(6),
        "trade_date": trade_date,
        "open": _required_decimal(row.get("open"), "open"),
        "high": _required_decimal(row.get("high"), "high"),
        "low": _required_decimal(row.get("low"), "low"),
        "close": _required_decimal(row.get("close"), "close"),
        "preclose": _required_decimal(row.get("pre_close"), "pre_close"),
        "volume": _required_decimal(row.get("vol"), "vol") * LOT_SIZE,
        "amount": _required_decimal(row.get("amount"), "amount") * THOUSAND,
        "turnover_rate": None,
        "pct_change": decimal_from(row.get("pct_chg")),
        "trade_status": True,
        "is_st": None,
    }


def normalize_akshare_daily(
    row: Mapping[str, Any], code: str | None = None
) -> dict[str, Any]:
    """AKShare ``stock_zh_a_daily`` (sina) row: volume in shares, amount yuan.

    The sina endpoint does not expose a code column or preclose; the caller
    supplies the requested code and preclose is intentionally left as None
    (the canonical row always comes from the selected provider, Tushare).
    """

    trade_date = parse_date_dash(row.get("date"))
    if trade_date is None:
        raise ValueError("akshare daily row has invalid date")
    raw_code = str(row.get("code") or code or "").split(".")[-1].zfill(6)
    turnover = decimal_from(row.get("turnover"))
    return {
        "code": raw_code,
        "trade_date": trade_date,
        "open": _required_decimal(row.get("open"), "open"),
        "high": _required_decimal(row.get("high"), "high"),
        "low": _required_decimal(row.get("low"), "low"),
        "close": _required_decimal(row.get("close"), "close"),
        "preclose": None,
        "volume": _required_decimal(row.get("volume"), "volume"),
        "amount": _required_decimal(row.get("amount"), "amount"),
        "turnover_rate": turnover * Decimal("100") if turnover is not None else None,
        "pct_change": None,
        "trade_status": True,
        "is_st": None,
    }


def normalize_tushare_daily_basic(row: Mapping[str, Any]) -> dict[str, Any]:
    trade_date = parse_date_yyyymmdd(row.get("trade_date"))
    if trade_date is None:
        raise ValueError("tushare daily_basic row has invalid trade_date")
    return {
        "code": row["ts_code"].split(".")[0].zfill(6),
        "trade_date": trade_date,
        "turnover_rate": decimal_from(row.get("turnover_rate")),
        "volume_ratio": decimal_from(row.get("volume_ratio")),
        "pe": decimal_from(row.get("pe")),
        "pb": decimal_from(row.get("pb")),
        "total_mv": decimal_from(row.get("total_mv")),
        "circ_mv": decimal_from(row.get("circ_mv")),
    }


def normalize_tushare_adj_factor(row: Mapping[str, Any]) -> dict[str, Any]:
    trade_date = parse_date_yyyymmdd(row.get("trade_date"))
    if trade_date is None:
        raise ValueError("tushare adj_factor row has invalid trade_date")
    return {
        "code": row["ts_code"].split(".")[0].zfill(6),
        "trade_date": trade_date,
        "adj_factor": _required_decimal(row.get("adj_factor"), "adj_factor"),
    }


def normalize_tushare_suspension(row: Mapping[str, Any]) -> dict[str, Any]:
    trade_date = parse_date_yyyymmdd(row.get("trade_date"))
    if trade_date is None:
        raise ValueError("tushare suspend_d row has invalid trade_date")
    return {
        "code": row["ts_code"].split(".")[0].zfill(6),
        "trade_date": trade_date,
        "suspend_type": as_text(row.get("suspend_type")),
        "suspend_timing": as_text(row.get("suspend_timing")),
    }


def normalize_tushare_price_limits(row: Mapping[str, Any]) -> dict[str, Any]:
    trade_date = parse_date_yyyymmdd(row.get("trade_date"))
    if trade_date is None:
        raise ValueError("tushare stk_limit row has invalid trade_date")
    return {
        "code": row["ts_code"].split(".")[0].zfill(6),
        "trade_date": trade_date,
        "up_limit": _required_decimal(row.get("up_limit"), "up_limit"),
        "down_limit": _required_decimal(row.get("down_limit"), "down_limit"),
    }


def normalize_tushare_stock_basic(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "code": row["ts_code"].split(".")[0].zfill(6),
        "name": as_text(row.get("name")),
        "industry": as_text(row.get("industry")),
        "market": as_text(row.get("market")),
        "list_date": parse_date_yyyymmdd(row.get("list_date")),
        "is_st": _st_from_name(as_text(row.get("name"))),
    }


def _st_from_name(name: str | None) -> bool | None:
    if name is None:
        return None
    upper = name.upper()
    if "ST" in upper:
        return True
    return False


def normalize_baostock_bar(bar: Any) -> dict[str, Any]:
    return {
        "code": bar.code,
        "trade_date": bar.trade_date,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "preclose": bar.preclose,
        "volume": bar.volume,
        "amount": bar.amount,
        "turnover_rate": bar.turnover_rate,
        "pct_change": bar.pct_change,
        "trade_status": bar.trade_status,
        "is_st": bar.is_st,
    }


def normalize_limit_up_record(record: Any) -> dict[str, Any]:
    first_seal = record.first_seal_time
    last_seal = record.last_seal_time
    return {
        "code": record.code,
        "trade_date": record.trade_date,
        "name": record.name,
        "limit_price": record.limit_price,
        "first_seal_time": first_seal.isoformat() if first_seal else None,
        "last_seal_time": last_seal.isoformat() if last_seal else None,
        "open_count": record.open_count,
        "consecutive_count": record.consecutive_count,
        "turnover_rate": record.turnover_rate,
        "float_market_cap": record.float_market_cap,
        "total_market_cap": record.total_market_cap,
        "industry": record.industry,
    }


def utc_now() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)
