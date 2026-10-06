"""Standalone script to fetch public historical 1H BTCUSDT data without API keys."""

import csv
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def download_btc_1h_data(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    total_candles: int = 8760,  # ~1 year of 1H candles
    output_file: str = "data/btcusdt_1h.csv",
) -> Path:
    """Download historical 1H candles from Binance public API."""
    out_path = Path(output_file).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base_url = "https://api.binance.com/api/v3/klines"
    limit = 1000  # Max per request

    all_klines = []
    end_time = None

    print(f"Fetching {total_candles} {interval} candles for {symbol} from public API...")

    while len(all_klines) < total_candles:
        fetch_limit = min(limit, total_candles - len(all_klines))
        url = f"{base_url}?symbol={symbol}&interval={interval}&limit={fetch_limit}"
        if end_time is not None:
            url += f"&endTime={end_time}"

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except Exception as err:
            print(f"Fetch error: {err}")
            break

        if not data:
            break

        # Klines returned in chronological order for that batch
        # If we page backwards using endTime, prepend to all_klines
        all_klines = data + all_klines
        # Next batch endTime is 1ms before the earliest candle in current batch
        earliest_open_time = data[0][0]
        end_time = earliest_open_time - 1
        print(f"Retrieved {len(all_klines)} candles (earliest: {datetime.fromtimestamp(earliest_open_time/1000, tz=timezone.utc).isoformat()})...")
        time.sleep(0.2)  # Respect public rate limits

    # Sort strictly by open time to ensure chronological order
    all_klines.sort(key=lambda k: k[0])

    # Remove duplicates if any
    unique_klines = []
    seen_times = set()
    for k in all_klines:
        if k[0] not in seen_times:
            seen_times.add(k[0])
            unique_klines.append(k)

    print(f"Total unique candles fetched: {len(unique_klines)}")

    # Write to standard CSV format
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for k in unique_klines:
            open_time_ms = k[0]
            dt_str = datetime.fromtimestamp(open_time_ms / 1000.0, tz=timezone.utc).isoformat()
            open_p = k[1]
            high_p = k[2]
            low_p = k[3]
            close_p = k[4]
            vol = k[5]
            writer.writerow([dt_str, open_p, high_p, low_p, close_p, vol])

    print(f"Dataset saved to: {out_path}")
    return out_path


if __name__ == "__main__":
    download_btc_1h_data()
