#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X-BOT PHONE KIVY LITE V1.1 — Fib 0.5 | MEXC | Android APK.

Лайт-версия без pandas/numpy + СМЕНА КЛЮЧЕЙ через приложение (keys.json).
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import threading, time, json, hmac, hashlib, importlib.util, csv
import requests
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput

APP_DIR = Path(__file__).resolve().parent
BASE = "https://contract.mexc.com"
PORTFOLIO_FILE = APP_DIR / "portfolio.json"
LIVE_DIR = APP_DIR / "live_candles"
KEYS_FILE = APP_DIR / "keys.json"
HTTP_TIMEOUT = 20
MAX_RETRIES = 3

LEVERAGE_DEFAULT = 10
POSITION_PCT_DEFAULT = 16.0
MAX_POSITIONS_DEFAULT = 1
RESERVE_PCT = 20.0
ZONE_PCT = 0.30
TP_PCT = 2.5
SL_PCT = 0.5
BE_PCT = 1.0

DEFAULT_PORTFOLIO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOTUSDT", "SUIUSDT"]
TFS = {"Min1": 4, "Min5": 48, "Min15": 144, "Min60": 720, "Hour4": 2880, "Day1": 14400}
STRATEGIES = ["Fib 0.5 1m", "Fib 0.5 5m", "Fib 0.5 15m", "Fib 0.5 60m", "Fib 0.5 4h", "Fib 0.5 1d"]

PIVOT_LEFT = 3
PIVOT_RIGHT = 3
PIVOT_THRESHOLD_PCT = 0.3
FIB_SIDE = 3
MAX_WAIT_MIN = 60
PULLBACK_PCT = 0.12
BTC_SOFT_DROP = -0.15
BTC_HARD_DROP = -0.30

INTERVAL_CANDIDATES = {
    "Min1": ["Min1", "1m"], "Min5": ["Min5", "5m"], "Min15": ["Min15", "15m"],
    "Min60": ["Min60", "60m"], "Hour4": ["Hour4", "4h"], "Day1": ["Day1", "1d"],
}
SYMBOL_CANDIDATES = ["US", "RAW"]
WORKING_FORMAT = {"interval": {}, "symbol": None}


def load_portfolio():
    try:
        if PORTFOLIO_FILE.exists():
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return [str(s).strip().upper() for s in data if str(s).strip()]
    except Exception:
        pass
    return list(DEFAULT_PORTFOLIO)


def load_keys():
    if KEYS_FILE.exists():
        try:
            with open(KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = data.get("MEXC_API_KEY", "")
            secret = data.get("MEXC_API_SECRET", "")
            if key and secret:
                return key, secret
        except Exception:
            pass
    p = APP_DIR / "mexc_config.py"
    if not p.exists():
        raise FileNotFoundError("НЕТ ФАЙЛА mexc_config.py")
    spec = importlib.util.spec_from_file_location("cfg", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.MEXC_API_KEY, m.MEXC_API_SECRET


def save_keys(api_key, api_secret):
    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump({"MEXC_API_KEY": api_key, "MEXC_API_SECRET": api_secret}, f, ensure_ascii=False, indent=2)


def headers(key, secret, body_str=""):
    ts = str(int(time.time() * 1000))
    sign = hmac.new(secret.encode(), (key + ts + body_str).encode(), hashlib.sha256).hexdigest()
    return {"ApiKey": key, "Request-Time": ts, "Signature": sign,
            "Content-Type": "application/json", "Accept": "application/json"}


def _request_with_retry(method, url, **kwargs):
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.request(method, url, timeout=HTTP_TIMEOUT, **kwargs)
            return r
        except requests.exceptions.RequestException as e:
            last_err = e
            time.sleep(1 + attempt)
    raise last_err


def api_get(key, secret, path, params=None):
    qs = ""
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = BASE + path + ("?" + qs if qs else "")
    r = _request_with_retry("GET", url, headers=headers(key, secret, qs))
    try:
        return r.json()
    except Exception:
        raise RuntimeError(f"HTTP {r.status_code} {url} {r.text[:200]}")


def api_post(key, secret, path, payload):
    body = json.dumps(payload, separators=(",", ":"))
    url = BASE + path
    r = _request_with_retry("POST", url, data=body, headers=headers(key, secret, body))
    try:
        return r.json()
    except Exception:
        raise RuntimeError(f"HTTP {r.status_code} {url} {r.text[:200]}")


def get_balance(key, secret):
    d = api_get(key, secret, "/api/v1/private/account/assets")
    if d.get("code") not in (0, "0"):
        return None, d.get("message", "API")
    for a in d.get("data", []):
        if a.get("currency") == "USDT":
            equity = float(a.get("equity", 0) or 0)
            available = float(a.get("availableBalance", equity) or 0)
            return {"equity": equity, "available": available}, "OK"
    return {"equity": 0.0, "available": 0.0}, "OK"


def get_contract(key, secret, symbol):
    d = api_get(key, secret, "/api/v1/contract/detail", {"symbol": symbol})
    if d.get("code") not in (0, "0"):
        raise RuntimeError(d.get("message", "contract detail"))
    data = d.get("data")
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError("contract detail")


def mexc_symbol(sym):
    return sym.replace("USDT", "_USDT")


def _symbol_for(sym, fmt):
    return mexc_symbol(sym) if fmt == "US" else sym


def fetch_klines(symbol, tf, hours):
    start_sec = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
    start_ms = start_sec * 1000
    intervals = [WORKING_FORMAT["interval"][tf]] if tf in WORKING_FORMAT["interval"] else INTERVAL_CANDIDATES[tf]
    symbols = [WORKING_FORMAT["symbol"]] if WORKING_FORMAT["symbol"] else SYMBOL_CANDIDATES
    last_err = None
    for iv in intervals:
        for sym_fmt in symbols:
            for start in (start_sec, start_ms):
                sym_url = _symbol_for(symbol, sym_fmt)
                url = f"{BASE}/api/v1/contract/kline/{sym_url}?interval={iv}&start={start}"
                for attempt in range(MAX_RETRIES):
                    try:
                        r = requests.get(url, timeout=HTTP_TIMEOUT)
                        d = r.json()
                        if r.status_code == 200 and d.get("code") in (0, "0") and d.get("data", {}).get("time"):
                            WORKING_FORMAT["interval"][tf] = iv
                            WORKING_FORMAT["symbol"] = sym_fmt
                            data = d["data"]
                            rows = []
                            for i in range(len(data["time"])):
                                rows.append({
                                    "time": int(data["time"][i]),
                                    "open": float(data["open"][i]),
                                    "high": float(data["high"][i]),
                                    "low": float(data["low"][i]),
                                    "close": float(data["close"][i]),
                                    "volume": float(data["vol"][i]),
                                })
                            return rows
                        last_err = f"HTTP {r.status_code} {str(d)[:120]}"
                        if d.get("code") in (0, "0") and not d.get("data", {}).get("time"):
                            time.sleep(1 + attempt)
                            continue
                    except Exception as e:
                        last_err = str(e)
                        time.sleep(1 + attempt)
    raise RuntimeError(f"kline: не удалось получить свечи ({last_err})")


def save_candles(symbol, tf, rows):
    LIVE_DIR.mkdir(exist_ok=True)
    p = LIVE_DIR / f"{symbol}_{tf}.csv"
    existing = {}
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    existing[int(row["time"])] = row
        except Exception:
            pass
    for r in rows:
        existing[r["time"]] = r
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for t in sorted(existing):
            w.writerow(existing[t])


def candle_downloader(log_fn, stop_event, symbols):
    log_fn(f"LIVE: подкачка свечей запущена ({len(symbols)} монет × 6 ТФ, каждые 30 сек).")
    while not stop_event.is_set():
        now = datetime.now(timezone.utc)
        ok = err = 0
        for sym in symbols:
            for tf, hours in TFS.items():
                try:
                    rows = fetch_klines(sym, tf, hours)
                    if rows:
                        save_candles(sym, tf, rows)
                        ok += 1
                    else:
                        err += 1
                except Exception as e:
                    err += 1
                    log_fn(f"LIVE {sym} {tf}: {e}")
        log_fn(f"LIVE: OK {ok} | ошибок {err} | {now.strftime('%H:%M:%S')} UTC")
        stop_event.wait(30)


def load_csv(sym, tf):
    p = LIVE_DIR / f"{sym}_{tf}.csv"
    if not p.exists():
        return None
    rows = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append({
                    "time": int(row["time"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                })
    except Exception:
        return None
    return rows if rows else None


def ema_series(values, n):
    k = 2 / (n + 1)
    out = []
    e = values[0]
    for v in values:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def enrich(rows):
    if not rows or len(rows) < 5:
        return rows
    closes = [r["close"] for r in rows]
    e20 = ema_series(closes, 20)
    e12 = ema_series(closes, 12)
    e26 = ema_series(closes, 26)
    macd_line = [a - b for a, b in zip(e12, e26)]
    macd_signal = ema_series(macd_line, 9)
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i-1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    ag, al = [], []
    g = gains[0] if gains else 0
    l = losses[0] if losses else 0
    for i in range(len(gains)):
        g = (g * 13 + gains[i]) / 14
        l = (l * 13 + losses[i]) / 14
        ag.append(g)
        al.append(l)
    for i, r in enumerate(rows):
        r["ema20"] = e20[i]
        r["macd_hist"] = macd_line[i] - macd_signal[i]
        rs = ag[i] / al[i] if al[i] else 100
        r["rsi14"] = 100 - 100 / (1 + rs)
        r["rsi_change"] = r["rsi14"] - rows[i-1].get("rsi14", r["rsi14"]) if i > 0 else 0
        r["macd_change"] = r["macd_hist"] - rows[i-1].get("macd_hist", r["macd_hist"]) if i > 0 else 0
    return rows


def zones(rows, n=100):
    z = []
    if not rows or len(rows) < 5:
        return z
    s = rows[-n:]
    for i in range(2, len(s) - 2):
        if s[i]["high"] == max(x["high"] for x in s[i-2:i+3]):
            z.append(("RES", s[i]["high"]))
        if s[i]["low"] == min(x["low"] for x in s[i-2:i+3]):
            z.append(("SUP", s[i]["low"]))
    return z


def touched(z, p, k):
    return any(a == k and abs(p - b) / b * 100 <= ZONE_PCT for a, b in z)


def trend(rows, t):
    if not rows:
        return 0
    q = [r for r in rows if r["time"] <= t]
    if not q:
        return 0
    r = q[-1]
    return 1 if r["close"] > r["ema20"] else (-1 if r["close"] < r["ema20"] else 0)


def causal_fib(d15, t, side):
    if not d15:
        return None
    h = [r for r in d15 if r["time"] < t]
    p = []
    for i in range(FIB_SIDE, len(h) - FIB_SIDE):
        if h[i]["low"] == min(x["low"] for x in h[i-FIB_SIDE:i+FIB_SIDE+1]):
            p.append((i, "L", h[i]["low"]))
        if h[i]["high"] == max(x["high"] for x in h[i-FIB_SIDE:i+FIB_SIDE+1]):
            p.append((i, "H", h[i]["high"]))
    if side == "LONG":
        a = [x for x in p if x[1] == "L"]
        if not a:
            return None
        ix, _, lo = a[-1]
        b = [x for x in p if x[1] == "H" and x[0] > ix]
        if not b:
            return None
        hi = b[-1][2]
    else:
        a = [x for x in p if x[1] == "H"]
        if not a:
            return None
        ix, _, hi = a[-1]
        b = [x for x in p if x[1] == "L" and x[0] > ix]
        if not b:
            return None
        lo = b[-1][2]
    return {"target": (hi + lo) / 2, "low": lo, "high": hi} if hi > lo else None


def check_signal(de, d15, d60, d4, d1d, entry_tf):
    de = enrich(de) if de else de
    if not de or len(de) < 5:
        return None
    z = zones(d1d) + zones(d4)
    n = len(d15)
    for i in range(max(PIVOT_LEFT, n - 6), n - PIVOT_RIGHT):
        k = i + PIVOT_RIGHT
        st = d15[k]["time"]
        tr = [trend(x, st) for x in (d1d, d4, d60)]
        wh = [x["high"] for x in d15[i-PIVOT_LEFT:i+PIVOT_RIGHT+1]]
        wl = [x["low"] for x in d15[i-PIVOT_LEFT:i+PIVOT_RIGHT+1]]
        side = None
        if d15[i]["low"] == min(wl) and tr == [1, 1, 1]:
            move = (max(x["high"] for x in d15[i:i+PIVOT_RIGHT+1]) - d15[i]["low"]) / d15[i]["low"] * 100
            r = d15[i+1]
            if move >= PIVOT_THRESHOLD_PCT and r["rsi_change"] > 0 and r["macd_change"] > 0:
                side = "LONG"
        if d15[i]["high"] == max(wh) and tr == [-1, -1, -1]:
            move = (d15[i]["high"] - min(x["low"] for x in d15[i:i+PIVOT_RIGHT+1])) / d15[i]["high"] * 100
            r = d15[i+1]
            if move >= PIVOT_THRESHOLD_PCT and r["rsi_change"] < 0 and r["macd_change"] < 0:
                side = "SHORT"
        if side is None:
            continue
        pl, ph = d15[i]["low"], d15[i]["high"]
        if side == "LONG" and not touched(z, pl, "SUP"):
            continue
        if side == "SHORT" and not touched(z, ph, "RES"):
            continue
        w = [x for x in de if st < x["time"] <= st + MAX_WAIT_MIN * 60]
        if side == "LONG":
            lim = pl * (1 + PULLBACK_PCT / 100)
            for j in range(len(w) - 1):
                r, nxt = w[j], w[j+1]
                if r["low"] <= lim and r["close"] > r["open"]:
                    fib = causal_fib(d15, nxt["time"], side)
                    return {"side": side, "entry_price": nxt["open"], "entry_time": nxt["time"], "fib": fib}
        else:
            lim = ph * (1 - PULLBACK_PCT / 100)
            for j in range(len(w) - 1):
                r, nxt = w[j], w[j+1]
                if r["high"] >= lim and r["close"] < r["open"]:
                    fib = causal_fib(d15, nxt["time"], side)
                    return {"side": side, "entry_price": nxt["open"], "entry_time": nxt["time"], "fib": fib}
    return None


def btc_filter(d15, de):
    try:
        if not d15 or not de or len(d15) < 3 or len(de) < 30:
            return "ALLOW", "NO_BTC_DATA"
        price_now = de[-1]["close"]
        p15 = d15[-2]["close"] if len(d15) > 1 else d15[-1]["close"]
        p30 = d15[-3]["close"] if len(d15) > 2 else p15
        drop15 = (price_now / p15 - 1) * 100
        drop30 = (price_now / p30 - 1) * 100
        below_ema20 = price_now < de[-1]["ema20"]
        below_ema50 = price_now < ema_series([r["close"] for r in de], 50)[-1]
        worst = min(drop15, drop30)
        if worst <= BTC_HARD_DROP and below_ema20 and below_ema50:
            return "BLOCK", "BTC_HARD_RISK_OFF"
        if worst <= BTC_SOFT_DROP and below_ema20:
            return "REDUCE", "BTC_SOFT_RISK_OFF"
        return "ALLOW", "BTC_OK"
    except Exception:
        return "ALLOW", "BTC_DATA_ERROR"


def extract_plan_id(d):
    data = d.get("data")
    if isinstance(data, (str, int)):
        return data
    if isinstance(data, dict):
        return data.get("orderId") or data.get("id")
    return None


class BotLogic:
    def __init__(self, log_fn):
        self.log_fn = log_fn
        self.key, self.secret = load_keys()
        self.positions = {}
        self.running = False
        self.stop_event = threading.Event()
        self.symbols = load_portfolio()
        self.symbol = "ВСЕ"
        self.strategy = "Fib 0.5 1m"
        self.leverage = LEVERAGE_DEFAULT
        self.position_pct = POSITION_PCT_DEFAULT
        self.max_positions = MAX_POSITIONS_DEFAULT

    def log(self, m):
        self.log_fn(m)

    def change_keys(self, api_key, api_secret):
        save_keys(api_key, api_secret)
        self.key, self.secret = load_keys()
        self.log_fn("КЛЮЧИ MEXC ОБНОВЛЕНЫ И СОХРАНЕНЫ НА ТЕЛЕФОНЕ.")

    def check_balance(self):
        try:
            b, s = get_balance(self.key, self.secret)
            if b is not None:
                self.log(f"Баланс: доступно {b['available']:.2f} | всего {b['equity']:.2f} USDT")
                return b
            self.log("MEXC: " + s)
        except Exception as e:
            self.log("ОШИБКА баланса: " + str(e))
        return None

    def _scope(self):
        return list(self.symbols) if self.symbol == "ВСЕ" else [self.symbol]

    def _get_all_positions(self):
        d = api_get(self.key, self.secret, "/api/v1/private/position/open_positions")
        result = {}
        for p in (d.get("data") or []):
            raw = str(p.get("symbol", ""))
            sym = raw.replace("_USDT", "USDT").replace("_", "")
            result[sym] = p
        return result

    def _get_position_id(self, sym):
        p = self._get_all_positions().get(sym)
        return (p.get("positionId") or p.get("id")) if p else None

    def _round_price(self, sym, price):
        try:
            info = get_contract(self.key, self.secret, sym)
            prec = int(info.get("pricePrecision", 1))
        except Exception:
            prec = 1
        return round(price, prec)

    def _has_position_tpsl(self, sym):
        position_id = self._get_position_id(sym)
        if not position_id:
            return False
        try:
            d = api_get(self.key, self.secret, "/api/v1/private/stoporder/list", {"positionId": position_id})
            if d.get("code") not in (0, "0"):
                return False
            data = d.get("data")
            if isinstance(data, dict):
                data = data.get("result") or data.get("orders") or data.get("data") or []
            return bool(data)
        except Exception:
            return False

    def sync_exchange(self):
        try:
            all_pos = self._get_all_positions()
            found = 0
            for sym in self._scope():
                data = [all_pos[sym]] if sym in all_pos else []
                if data:
                    p = data[0]
                    ptype = p.get("positionType")
                    hold = p.get("holdSide")
                    if str(ptype) == "1":
                        side = "LONG"
                    elif str(ptype) == "2":
                        side = "SHORT"
                    elif str(hold).upper() in ("1", "LONG"):
                        side = "LONG"
                    elif str(hold).upper() in ("2", "SHORT"):
                        side = "SHORT"
                    else:
                        side = "UNKNOWN"
                    entry = float(p.get("openAvgPrice") or p.get("holdAvgPrice") or 0)
                    vol = float(p.get("holdVol") or p.get("positionVol") or 0)
                    self.log(f"СИНХРОНИЗАЦИЯ: {side} {sym} @ {entry:.2f} vol={vol} | positionType={ptype}")
                    if sym not in self.positions:
                        self.positions[sym] = {"side": side, "entry": entry, "vol": vol, "be": False, "fib": None, "margin": 0.0, "tp_id": None, "sl_id": None, "tps_applied": False}
                    else:
                        self.positions[sym].update({"side": side, "entry": entry, "vol": vol})
                    found += 1
            self.log(f"СИНХРОНИЗАЦИЯ: найдено позиций: {found}")
            self._apply_strategy_all()
        except Exception as e:
            self.log("ОШИБКА синхронизации: " + str(e))

    def _apply_strategy_all(self):
        for sym in list(self.positions.keys()):
            self._apply_strategy_to_position(sym)

    def _apply_strategy_to_position(self, sym):
        pos = self.positions.get(sym)
        if not pos or pos.get("tps_applied"):
            return
        if pos["side"] == "UNKNOWN":
            self.log(f"ОШИБКА: не удалось определить сторону {sym}.")
            return
        self.log(f"ПРИМЕНЯЮ СТРАТЕГИЮ {self.strategy} к {sym} (SAFE).")
        price = None
        d1 = load_csv(sym, "Min1")
        if d1:
            price = d1[-1]["close"]
        if price is None:
            price = pos["entry"]
        try:
            if self._has_position_tpsl(sym):
                self.log(f"SAFE: TP/SL уже привязаны к позиции {sym} — не дублирую.")
                pos["tps_applied"] = True
                return
            tp_id, sl_id, tp_price, sl_price = self._place_tpsl(sym, pos["side"], price, pos["vol"])
            pos["tp_id"] = tp_id
            pos["sl_id"] = sl_id
            pos["tps_applied"] = True
            self.log(f"СТРАТЕГИЯ ПРИМЕНЕНА: {sym} TP={tp_price} SL={sl_price}")
        except Exception as e:
            self.log("ОШИБКА TP/SL " + sym + ": " + str(e))

    def _place_tpsl(self, sym, side, price, vol):
        position_id = self._get_position_id(sym)
        if not position_id:
            raise RuntimeError("не найден positionId для " + sym)
        if side == "LONG":
            tp = self._round_price(sym, price * (1 + TP_PCT / 100))
            sl = self._round_price(sym, price * (1 - SL_PCT / 100))
        else:
            tp = self._round_price(sym, price * (1 - TP_PCT / 100))
            sl = self._round_price(sym, price * (1 + SL_PCT / 100))
        payload = {"positionId": position_id, "vol": vol,
                   "takeProfitPrice": tp, "stopLossPrice": sl,
                   "volType": 2, "stopLossType": 0, "profitLossVolType": "SAME"}
        d = api_post(self.key, self.secret, "/api/v1/private/stoporder/place", payload)
        if d.get("code") not in (0, "0"):
            msg = str(d.get("message", ""))
            if "already a position TP/SL" in msg:
                self.log(f"SAFE: TP/SL уже привязаны к позиции {sym} — не дублирую.")
                return None, None, tp, sl
            raise RuntimeError(msg or "stoporder")
        self.log(f"TP/SL {sym} ПРИВЯЗАНЫ К СДЕЛКЕ: TP={tp} | SL={sl}")
        return extract_plan_id(d), extract_plan_id(d), tp, sl

    def _cancel_protectives(self, sym):
        pos = self.positions.get(sym)
        if not pos:
            return
        position_id = self._get_position_id(sym)
        if position_id:
            try:
                api_post(self.key, self.secret, "/api/v1/private/stoporder/cancel", {"positionId": position_id})
                self.log(f"Отменены TP/SL позиции {sym}.")
            except Exception as e:
                self.log(f"ОШИБКА отмены TP/SL {sym}: {str(e)}")
        pos["tp_id"] = None
        pos["sl_id"] = None

    def _calc_margin(self, available, risk=1.0):
        usable = available * (1 - RESERVE_PCT / 100)
        margin = usable * self.position_pct / 100 * risk
        self.log(f"Баланс {available:.2f} | резерв {RESERVE_PCT}% | маржа {margin:.2f}")
        return margin

    def _calc_vol(self, price, info, margin, leverage):
        size = float(info.get("contractSize", 0.0001))
        minv = float(info.get("minVol", 1))
        vol = margin * leverage / (price * size)
        vol = max(minv, round(vol / minv) * minv)
        return round(vol, 8)

    def _place_market(self, sym, side, price, vol, leverage):
        payload = {"symbol": sym, "price": price, "vol": vol, "leverage": leverage, "side": side, "type": 5, "openType": 1}
        d = api_post(self.key, self.secret, "/api/v1/private/order/submit", payload)
        if d.get("code") not in (0, "0"):
            raise RuntimeError(d.get("message", "order"))
        return d

    def _count_open_positions(self):
        try:
            return len(self._get_all_positions())
        except Exception as e:
            self.log("ОШИБКА подсчёта позиций: " + str(e))
            return 999

    def _has_open_position(self, sym):
        try:
            return sym in self._get_all_positions()
        except Exception as e:
            self.log("ОШИБКА проверки позиции " + sym + ": " + str(e))
            return True

    def start_auto(self):
        if self.running:
            return
        self.running = True
        self.log("АВТО-РЕЖИМ ЗАПУЩЕН: " + ("ВСЕ" if self.symbol == "ВСЕ" else self.symbol))
        self.sync_exchange()
        threading.Thread(target=self._autoloop, daemon=True).start()

    def stop_auto(self):
        self.running = False
        self.log("АВТО-РЕЖИМ ОСТАНОВЛЕН.")

    def _autoloop(self):
        while self.running:
            try:
                open_count = self._count_open_positions()
                for sym in self._scope():
                    pos = self.positions.get(sym)
                    if pos:
                        d1 = load_csv(sym, "Min1")
                        price = d1[-1]["close"] if d1 else pos["entry"]
                        if not self._has_open_position(sym):
                            self.log(f"Позиция {sym} закрыта на бирже — отменяю TP/SL.")
                            self._cancel_protectives(sym)
                            self.positions.pop(sym, None)
                            continue
                        self._manage(sym, price)
                    else:
                        if not self._has_open_position(sym) and open_count < self.max_positions:
                            sig = self._check_signal_for(sym)
                            if sig:
                                action, reason = self._btc_filter_for(sym)
                                if action == "BLOCK":
                                    self.log(f"BTC-фильтр BLOCK {sig['side']} {sym}: {reason}")
                                else:
                                    risk = 0.5 if action == "REDUCE" else 1.0
                                    self._open(sig, sym, sig["entry_price"], risk)
                                    open_count += 1
            except Exception as e:
                self.log("AUTO ОШИБКА: " + str(e))
            time.sleep(5)

    def _check_signal_for(self, sym):
        tf = self.strategy.split()[-1]
        iv_map = {"1m": "Min1", "5m": "Min5", "15m": "Min15", "60m": "Min60", "4h": "Hour4", "1d": "Day1"}
        de = load_csv(sym, iv_map[tf])
        d15 = enrich(load_csv(sym, "Min15"))
        d60 = enrich(load_csv(sym, "Min60"))
        d4 = enrich(load_csv(sym, "Hour4"))
        d1d = enrich(load_csv(sym, "Day1"))
        return check_signal(de, d15, d60, d4, d1d, tf)

    def _btc_filter_for(self, sym):
        d15 = enrich(load_csv(sym, "Min15"))
        de = enrich(load_csv(sym, "Min1"))
        return btc_filter(d15, de)

    def _open(self, sig, sym, price, risk=1.0):
        b = self.check_balance()
        if b is None or b["available"] <= 0:
            self.log("ОШИБКА: нет доступного баланса.")
            return
        margin = self._calc_margin(b["available"], risk)
        info = get_contract(self.key, self.secret, sym)
        vol = self._calc_vol(price, info, margin, self.leverage)
        side = sig["side"]
        self._place_market(sym, 1 if side == "LONG" else 3, price, vol, self.leverage)
        self.log(f"ОТКРЫТ {side} {sym} @ {price:.2f} vol={vol}")
        try:
            tp_id, sl_id, tp_price, sl_price = self._place_tpsl(sym, side, price, vol)
        except Exception as e:
            self.log("ОШИБКА TP/SL: " + str(e))
        self.positions[sym] = {"side": side, "entry": price, "vol": vol, "be": False, "fib": sig["fib"], "margin": margin, "tp_id": tp_id, "sl_id": sl_id, "tps_applied": True}
        self.log(f"СИГНАЛ {side} {sym} @ {price:.2f}")

    def _manage(self, sym, price):
        pos = self.positions.get(sym)
        if not pos:
            return
        if pos["side"] == "LONG":
            be_trigger = pos["entry"] * (1 + BE_PCT / 100)
            if not pos["be"] and price >= be_trigger:
                pos["be"] = True
                self.log(f"BE включён: {sym}")
                try:
                    self._cancel_protectives(sym)
                    new_sl = round(pos["entry"], 2)
                    tp_id, sl_id, tp_price, sl_price = self._place_tpsl(sym, pos["side"], new_sl, pos["vol"])
                    pos["tp_id"] = tp_id
                    pos["sl_id"] = sl_id
                    self.log(f"SL переставлен в BE: {new_sl}")
                except Exception as e:
                    self.log("ОШИБКА BE: " + str(e))
        else:
            be_trigger = pos["entry"] * (1 - BE_PCT / 100)
            if not pos["be"] and price <= be_trigger:
                pos["be"] = True
                self.log(f"BE включён: {sym}")
                try:
                    self._cancel_protectives(sym)
                    new_sl = round(pos["entry"], 2)
                    tp_id, sl_id, tp_price, sl_price = self._place_tpsl(sym, pos["side"], new_sl, pos["vol"])
                    pos["tp_id"] = tp_id
                    pos["sl_id"] = sl_id
                    self.log(f"SL переставлен в BE: {new_sl}")
                except Exception as e:
                    self.log("ОШИБКА BE: " + str(e))


class PhoneBotApp(App):
    def build(self):
        self.title = "X-BOT PHONE KIVY LITE V1.1"
        self.logic = None
        self.stop_event = threading.Event()
        root = BoxLayout(orientation="vertical", padding=10, spacing=8)
        root.add_widget(Label(text="X-BOT PHONE KIVY LITE V1.1 — Fib 0.5 | MEXC", size_hint_y=None, height=40, bold=True))
        self.balance_lbl = Label(text="Баланс: —", size_hint_y=None, height=30, color=(0.2, 0.8, 0.6, 1))
        root.add_widget(self.balance_lbl)
        btns = BoxLayout(size_hint_y=None, height=50, spacing=6)
        btns.add_widget(Button(text="БАЛАНС", on_press=self.on_balance))
        btns.add_widget(Button(text="СИНХРОНИЗИРОВАТЬ", on_press=self.on_sync))
        btns.add_widget(Button(text="СТАРТ", on_press=self.on_start, background_color=(0.1, 0.6, 0.3, 1)))
        btns.add_widget(Button(text="СТОП", on_press=self.on_stop, background_color=(0.6, 0.2, 0.2, 1)))
        root.add_widget(btns)
        btns2 = BoxLayout(size_hint_y=None, height=50, spacing=6)
        btns2.add_widget(Button(text="КЛЮЧИ MEXC", on_press=self.on_keys, background_color=(0.2, 0.4, 0.8, 1)))
        root.add_widget(btns2)
        self.status = Label(text="Готов к работе", size_hint_y=None, height=30)
        root.add_widget(self.status)
        root.add_widget(Label(text="ЛОГ", size_hint_y=None, height=25, bold=True))
        scroll = ScrollView()
        self.log_label = Label(text="", size_hint_y=None, halign="left", valign="top")
        self.log_label.bind(width=lambda *x: self.log_label.setter("text_size")(self.log_label, (self.log_label.width, None)))
        scroll.add_widget(self.log_label)
        root.add_widget(scroll)
        threading.Thread(target=candle_downloader, args=(self.log, self.stop_event, load_portfolio()), daemon=True).start()
        return root

    def log(self, m):
        self.log_label.text += m + "\n"

    def on_balance(self, instance):
        if not self.logic:
            self.logic = BotLogic(self.log)
        self.logic.check_balance()

    def on_sync(self, instance):
        if not self.logic:
            self.logic = BotLogic(self.log)
        self.logic.sync_exchange()

    def on_start(self, instance):
        if not self.logic:
            self.logic = BotLogic(self.log)
        self.logic.start_auto()
        self.status.text = "АВТО-РЕЖИМ ЗАПУЩЕН"

    def on_stop(self, instance):
        if self.logic:
            self.logic.stop_auto()
        self.status.text = "АВТО-РЕЖИМ ОСТАНОВЛЕН"

    def on_keys(self, instance):
        box = BoxLayout(orientation="vertical", padding=10, spacing=8)
        box.add_widget(Label(text="Новый API Key:"))
        key_input = TextInput(multiline=False)
        box.add_widget(key_input)
        box.add_widget(Label(text="Новый Secret:"))
        secret_input = TextInput(multiline=False, password=True)
        box.add_widget(secret_input)
        def save_keys(instance):
            k = key_input.text.strip()
            s = secret_input.text.strip()
            if k and s:
                if not self.logic:
                    self.logic = BotLogic(self.log)
                self.logic.change_keys(k, s)
                popup.dismiss()
            else:
                self.log("ОШИБКА: заполни оба поля.")
        box.add_widget(Button(text="СОХРАНИТЬ КЛЮЧИ", on_press=save_keys, background_color=(0.1, 0.6, 0.3, 1)))
        popup = Popup(title="Смена ключей MEXC (раз в 90 дней)", content=box, size_hint=(0.9, 0.6))
        popup.open()


if __name__ == "__main__":
    PhoneBotApp().run()
