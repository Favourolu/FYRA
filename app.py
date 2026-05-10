import os
import re
import csv
import json
import queue
import atexit
import base64
import threading
import io as _io
import time as _time
import socket as _socket
from datetime import datetime as _dt
from flask import Flask, render_template, request, redirect
from flask_socketio import SocketIO, emit
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
if not ANTHROPIC_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

import anthropic
import intent as intent_module
import assistant
import memory as memory_module
import db as _db
from db import BudgetExceeded
from config import MODEL_FAST
from tools import fetch_afriterminal_data

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # HTTPS on Railway
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

FYRA_TOKEN = os.getenv("FYRA_ACCESS_TOKEN", "").strip()

# sid → "favour" | "fiyin" — tracks connected known users for proactive features
_connected_known: dict = {}

# Last AfriTerminal market_summary Last-Modified seen by the monitor job
_last_market_ts: str = ""

# sid → pre-built chart list, held until user requests it
_pending_charts: dict = {}


def _local_ip() -> str:
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def _strip_md(text: str) -> str:
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)   # bold/italic
    text = re.sub(r'#{1,6}\s+', '', text)                    # headers
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)           # code
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.M)    # bullets
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.M)    # numbered lists
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)   # links
    text = re.sub(r'\|', ' ', text)                          # table pipes
    text = re.sub(r'[{}\[\]]', '', text)                     # brackets
    text = re.sub(r'\n+', ' ', text).strip()
    return text


def _tts(text: str):
    api_key = os.getenv("FISH_AUDIO_API_KEY", "").strip()
    if not api_key:
        print("[TTS] No FISH_AUDIO_API_KEY set — skipping voice")
        return None
    try:
        import requests
        import msgpack
        voice_id = os.getenv("FISH_AUDIO_VOICE_ID", "").strip() or "329ff0b9604444ec982526af54630427"
        payload = {"text": text, "format": "mp3", "latency": "normal", "reference_id": voice_id}
        print(f"[TTS] Requesting voice | id={voice_id or '(default)'} | len={len(text)}")
        r = requests.post(
            "https://api.fish.audio/v1/tts",
            data=msgpack.packb(payload, use_bin_type=True),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/msgpack",
            },
            timeout=30,
            stream=True,
        )
        if not r.ok:
            print(f"[TTS] Error {r.status_code}: {r.text[:200]}")
            return None
        audio_bytes = b"".join(r.iter_content(chunk_size=4096))
        print(f"[TTS] OK — {len(audio_bytes)} bytes")
        return base64.b64encode(audio_bytes).decode("utf-8")
    except Exception as e:
        print(f"[TTS] Exception: {e}")
        return None


def _generate_greeting(addressed_name: str, memory_context: str) -> str:
    from datetime import datetime
    hour = datetime.now().hour
    time_of_day = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    brief = memory_module.get_startup_brief()
    context = memory_context + (f"\nAlerts: {brief}" if brief else "")
    response = _client.messages.create(
        model=MODEL_FAST,
        max_tokens=80,
        system=(
            "You are Fyra, a personal AI inspired by J.A.R.V.I.S. "
            "Write exactly one short greeting sentence spoken aloud — no markdown, no lists. "
            "Use the person's name. Weave in the time of day naturally. "
            "If context has open tasks or upcoming events, mention one briefly. "
            "Be warm but efficient."
        ),
        messages=[{"role": "user", "content": f"Greet {addressed_name}. Time of day: {time_of_day}.\nContext:\n{context}"}],
    )
    _db.track_usage(MODEL_FAST, response.usage.input_tokens, response.usage.output_tokens)
    return response.content[0].text.strip()


def _build_chart_data(dataset: str, raw: str):
    """Parse AfriTerminal raw text into a list of Chart.js-ready dicts. Returns [] on failure."""
    charts = []
    try:
        body = "\n".join(raw.split("\n")[1:]).strip()  # strip AfriTerminal header

        if dataset == "market_summary":
            data    = json.loads(body)
            gainers = data.get("top_gainers", [])[:8]
            losers  = data.get("top_losers",  [])[:8]
            breadth = data.get("market", {})
            if gainers:
                charts.append({
                    "type": "bar", "title": "NGX Top Gainers",
                    "labels": [g.get("ticker") or g.get("symbol", "") for g in gainers],
                    "datasets": [{"label": "Change %",
                                  "data": [round(float(g.get("change") or g.get("change_pct", 0)), 2) for g in gainers]}],
                })
            if losers:
                charts.append({
                    "type": "bar", "title": "NGX Top Losers",
                    "labels": [l.get("ticker") or l.get("symbol", "") for l in losers],
                    "datasets": [{"label": "Change %",
                                  "data": [round(float(l.get("change") or l.get("change_pct", 0)), 2) for l in losers]}],
                })
            if breadth:
                charts.append({
                    "type": "doughnut", "title": "Market Breadth",
                    "labels": ["Gainers", "Decliners", "Unchanged"],
                    "datasets": [{"label": "Stocks",
                                  "data": [breadth.get("gainers", 0), breadth.get("decliners", 0), breadth.get("unchanged", 0)]}],
                })

        elif dataset == "ngx_prices":
            # CSV: Ticker,Name,Price,Change%,Timestamp
            rows = []
            for row in csv.DictReader(_io.StringIO(body)):
                try:
                    chg = float(row.get("Change%", 0) or 0)
                    rows.append({"symbol": row.get("Ticker", ""), "change_pct": chg})
                except Exception:
                    continue
            gainers = sorted([r for r in rows if r["change_pct"] > 0], key=lambda r: r["change_pct"], reverse=True)[:10]
            losers  = sorted([r for r in rows if r["change_pct"] < 0], key=lambda r: r["change_pct"])[:8]
            if gainers:
                charts.append({
                    "type": "bar", "title": "NGX Top Gainers (Live)",
                    "labels": [r["symbol"] for r in gainers],
                    "datasets": [{"label": "Change %", "data": [round(r["change_pct"], 2) for r in gainers]}],
                })
            if losers:
                charts.append({
                    "type": "bar", "title": "NGX Top Losers (Live)",
                    "labels": [r["symbol"] for r in losers],
                    "datasets": [{"label": "Change %", "data": [round(r["change_pct"], 2) for r in losers]}],
                })

        elif dataset == "fx":
            # CSV: Currency,Rate_vs_USD,Updated
            rows = []
            for row in csv.DictReader(_io.StringIO(body)):
                try:
                    rows.append({"currency": row.get("Currency", ""),
                                 "rate": float(row.get("Rate_vs_USD", 0) or 0)})
                except Exception:
                    continue
            if rows:
                charts.append({
                    "type": "bar", "title": "African Currencies vs USD",
                    "labels": [r["currency"] for r in rows],
                    "datasets": [{"label": "Units per USD", "data": [round(r["rate"], 2) for r in rows]}],
                })

        elif dataset == "bonds":
            data      = json.loads(body)
            countries = data.get("countries", {})
            for country, info in list(countries.items())[:4]:
                curve = info.get("yield_curve", [])
                if curve:
                    charts.append({
                        "type": "line", "title": f"{country} Bond Yield Curve",
                        "labels": [p.get("tenor", "") for p in curve],
                        "datasets": [{"label": "Yield %",
                                      "data": [round(float(p.get("yield", 0)), 2) for p in curve]}],
                    })

        elif dataset == "macro":
            # CSV: Country,Indicator,Value,Year
            by_indicator: dict = {}
            for row in csv.DictReader(_io.StringIO(body)):
                ind, country = row.get("Indicator", ""), row.get("Country", "")
                try:
                    val = float(row.get("Value", 0) or 0)
                except Exception:
                    continue
                by_indicator.setdefault(ind, {})[country] = val

            for ind_name, country_vals in by_indicator.items():
                if not country_vals:
                    continue
                divisor = 1e9 if "GDP" in ind_name else 1
                label   = ind_name.replace("(USD)", "(B USD)") if divisor > 1 else ind_name
                charts.append({
                    "type": "bar", "title": ind_name,
                    "labels": list(country_vals.keys()),
                    "datasets": [{"label": label,
                                  "data": [round(v / divisor, 2) for v in country_vals.values()]}],
                })

        elif dataset == "global":
            data    = json.loads(body)
            indices = data.get("indices", [])[:8]
            if indices:
                charts.append({
                    "type": "bar", "title": "Global Markets — Change %",
                    "labels": [i.get("name") or i.get("ticker", "") for i in indices],
                    "datasets": [{"label": "Change %",
                                  "data": [round(float(i.get("change_pct", 0)), 2) for i in indices]}],
                })
            for idx in indices[:2]:
                hist = idx.get("chart_1mo", [])
                if len(hist) > 5:
                    charts.append({
                        "type": "line", "title": f"{idx.get('name', '')} — 1 Month",
                        "labels": [p.get("t", "")[-5:] for p in hist],
                        "datasets": [{"label": "Close",
                                      "data": [round(float(p.get("c", 0)), 2) for p in hist]}],
                    })

        elif dataset == "market_flows":
            data   = json.loads(body)
            period = data.get("period", "")
            charts.append({
                "type": "doughnut", "title": f"Market Participation ({period})",
                "labels": ["Domestic Institutional", "Domestic Retail", "Foreign Net"],
                "datasets": [{"label": "₦ Trillions",
                              "data": [
                                  round(data.get("domestic_institutional", 0) / 1e12, 2),
                                  round(data.get("domestic_retail",        0) / 1e12, 2),
                                  round(abs(data.get("foreign_net",        0)) / 1e12, 3),
                              ]}],
            })
            charts.append({
                "type": "bar", "title": f"Foreign Flows ({period})",
                "labels": ["Inflows", "Outflows", "Net"],
                "datasets": [{"label": "₦ Billions",
                              "data": [
                                  round(data.get("foreign_inflows",  0) / 1e9, 1),
                                  round(data.get("foreign_outflows", 0) / 1e9, 1),
                                  round(data.get("foreign_net",      0) / 1e9, 1),
                              ]}],
            })

    except Exception as e:
        print(f"[Chart] parse error for {dataset}: {e}")
    return charts


def _pick_chart_dataset(user_text: str) -> str:
    """Choose the most relevant AfriTerminal dataset to chart based on the user's query."""
    lower = user_text.lower()
    if any(w in lower for w in ("fx", "exchange rate", "naira", "dollar", "pound", "euro", "currency", "usd", "gbp")):
        return "fx"
    if any(w in lower for w in ("bond", "yield", "treasury", "sovereign", "fgn bond", "tenor", "debt")):
        return "bonds"
    if any(w in lower for w in ("global", "s&p", "s&p 500", "ftse", "dow", "nikkei", "nasdaq", "dax", "oil", "gold", "international", "world market")):
        return "global"
    if any(w in lower for w in ("flow", "institutional", "foreign investor", "participation", "retail investor", "turnover", "capital")):
        return "market_flows"
    if any(w in lower for w in ("inflation", "gdp", "macro", "unemployment", "growth rate", "cpi", "economy")):
        return "macro"
    if any(w in lower for w in ("price", "live", "all share", "ngx stock", "stock price", "share price")):
        return "ngx_prices"
    return "market_summary"


def _push_market_brief(sid: str):
    """Called in a background thread — waits 3s then sends a spoken market brief."""
    _time.sleep(3)
    if sid not in _connected_known:
        return
    market_raw = fetch_afriterminal_data("market_summary")
    fx_raw     = fetch_afriterminal_data("fx")
    if "[FAILED]" in market_raw and "[FAILED]" in fx_raw:
        return

    combined = ""
    if "[FAILED]" not in market_raw:
        combined += market_raw[:2000]
    if "[FAILED]" not in fx_raw:
        combined += "\n" + fx_raw[:1000]

    try:
        resp = _client.messages.create(
            model=MODEL_FAST,
            max_tokens=100,
            system=(
                "You are Fyra, a personal AI. Deliver a 2-sentence market brief spoken aloud. "
                "No markdown, no lists. Mention 1-2 key NGX moves and the USD/NGN rate. "
                "Be concise and natural."
            ),
            messages=[{"role": "user", "content": f"Market data:\n{combined}"}],
        )
        _db.track_usage(MODEL_FAST, resp.usage.input_tokens, resp.usage.output_tokens)
        brief = resp.content[0].text.strip()
    except Exception:
        return

    socketio.emit("proactive_brief", {"text": brief}, to=sid)
    audio = _tts(brief)
    if audio:
        socketio.emit("audio_chunk", {"audio": audio}, to=sid)


# ── Google Calendar helpers ───────────────────────────────────

def _google_flow():
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config(
        {
            "web": {
                "client_id":     os.getenv("GOOGLE_CLIENT_ID", ""),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": [os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5000/auth/google/callback")],
            }
        },
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
        redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5000/auth/google/callback"),
    )


def get_upcoming_events(person: str) -> str:
    """Return next 3 calendar events as a string, or empty string if unavailable."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        import db as _db
        with _db.get_db_conn() as conn:
            row = conn.execute(
                "SELECT access_token, refresh_token, expiry, scopes FROM calendar_tokens WHERE person=?",
                (person,)
            ).fetchone()
        if not row:
            return ""
        creds = Credentials(
            token=row["access_token"],
            refresh_token=row["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
            scopes=(row["scopes"] or "").split(),
        )
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            with _db.get_db_conn() as conn:
                conn.execute(
                    "UPDATE calendar_tokens SET access_token=?, expiry=? WHERE person=?",
                    (creds.token, str(creds.expiry), person)
                )
                conn.commit()

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        now = _dt.utcnow().isoformat() + "Z"
        result = service.events().list(
            calendarId="primary", timeMin=now, maxResults=3,
            singleEvents=True, orderBy="startTime"
        ).execute()
        items = result.get("items", [])
        if not items:
            return ""
        lines = []
        for e in items:
            start = e["start"].get("dateTime", e["start"].get("date", ""))[:16]
            lines.append(f"  {start}: {e.get('summary', 'Untitled event')}")
        return "Upcoming calendar events:\n" + "\n".join(lines)
    except Exception:
        return ""


# ── Scheduled jobs ────────────────────────────────────────────

def _scheduled_morning_brief():
    for sid in list(_connected_known.keys()):
        threading.Thread(target=_push_market_brief, args=(sid,), daemon=True).start()


def _check_watchlist_alerts():
    """Compare watchlist tickers against ngx_prices; alert on >3% moves."""
    prices_raw = fetch_afriterminal_data("ngx_prices")
    if "[FAILED]" in prices_raw:
        return
    import csv as _csv
    body = "\n".join(prices_raw.split("\n")[1:]).strip()
    price_map = {}
    for row in _csv.DictReader(_io.StringIO(body)):
        sym = (row.get("symbol") or "").strip().upper()
        try:
            price_map[sym] = float(row.get("price", 0) or 0)
        except Exception:
            continue

    with _db.get_db_conn() as conn:
        wl_rows = conn.execute(
            "SELECT person, value FROM profiles WHERE field='watchlist'"
        ).fetchall()

    now_str = _dt.utcnow().isoformat()[:16]
    alerts = []
    for row in wl_rows:
        person = row["person"]
        try:
            tickers = json.loads(row["value"])
        except Exception:
            continue
        for ticker in tickers:
            ticker_up = ticker.strip().upper()
            if ticker_up not in price_map:
                continue
            current = price_map[ticker_up]
            with _db.get_db_conn() as conn:
                prev_row = conn.execute(
                    "SELECT price FROM watchlist_prices WHERE person=? AND ticker=?",
                    (person, ticker_up)
                ).fetchone()
            if prev_row and prev_row["price"]:
                prev = prev_row["price"]
                pct_change = abs(current - prev) / prev * 100 if prev else 0
                if pct_change >= 3.0:
                    direction = "up" if current > prev else "down"
                    alerts.append(
                        f"{ticker_up} is {direction} {pct_change:.1f}% to {current:.2f} for {person.capitalize()}"
                    )
            with _db.get_db_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO watchlist_prices (person, ticker, price, checked_at) VALUES (?, ?, ?, ?)",
                    (person, ticker_up, current, now_str)
                )
                conn.commit()

    if alerts:
        alert_text = "Watchlist alert: " + "; ".join(alerts) + "."
        for sid, person in list(_connected_known.items()):
            socketio.emit("proactive_brief", {"text": alert_text}, to=sid)
            audio = _tts(alert_text)
            if audio:
                socketio.emit("audio_chunk", {"audio": audio}, to=sid)


def _scheduled_market_monitor():
    global _last_market_ts
    if not _connected_known:
        return
    raw = fetch_afriterminal_data("market_summary")
    if "[FAILED]" in raw:
        return
    # Extract Last-Modified from the header line
    header_line = raw.split("\n")[0]
    ts_marker = "data as of: "
    idx = header_line.find(ts_marker)
    ts = header_line[idx + len(ts_marker):].strip() if idx != -1 else ""
    if ts and ts != _last_market_ts and _last_market_ts:
        _last_market_ts = ts
        try:
            resp = _client.messages.create(
                model=MODEL_FAST,
                max_tokens=60,
                system="You are Fyra. Write one spoken sentence alerting the user that fresh market data is available. Mention 1 key change. No markdown.",
                messages=[{"role": "user", "content": raw[:1500]}],
            )
            _db.track_usage(MODEL_FAST, resp.usage.input_tokens, resp.usage.output_tokens)
            alert = resp.content[0].text.strip()
            for sid in list(_connected_known.keys()):
                socketio.emit("proactive_brief", {"text": alert}, to=sid)
                audio = _tts(alert)
                if audio:
                    socketio.emit("audio_chunk", {"audio": audio}, to=sid)
        except Exception:
            pass
    elif not _last_market_ts:
        _last_market_ts = ts
    _check_watchlist_alerts()


def _scheduled_eod_summary():
    if not _connected_known:
        return
    today_start = _dt.utcnow().strftime("%Y-%m-%dT00:00:00")
    with _db.get_db_conn() as conn:
        rows = conn.execute(
            "SELECT user_text, fyra_text FROM conversations WHERE timestamp >= ? ORDER BY id ASC",
            (today_start,)
        ).fetchall()
    if not rows:
        return
    convo_summary = "\n".join(f"User: {r['user_text'][:100]}\nFyra: {r['fyra_text'][:150]}" for r in rows[-10:])
    market_raw    = fetch_afriterminal_data("market_summary")
    market_snip   = "" if "[FAILED]" in market_raw else market_raw[:800]
    try:
        resp = _client.messages.create(
            model=MODEL_FAST,
            max_tokens=120,
            system=(
                "You are Fyra. Deliver a 3-sentence end-of-day spoken summary. "
                "Cover: what was discussed today, any open tasks, and one market highlight. "
                "No markdown, no lists. Sound warm and efficient."
            ),
            messages=[{"role": "user", "content": f"Today's conversations:\n{convo_summary}\n\nMarket data:\n{market_snip}"}],
        )
        _db.track_usage(MODEL_FAST, resp.usage.input_tokens, resp.usage.output_tokens)
        summary = resp.content[0].text.strip()
    except Exception:
        return
    for sid in list(_connected_known.keys()):
        socketio.emit("proactive_brief", {"text": summary}, to=sid)
        audio = _tts(summary)
        if audio:
            socketio.emit("audio_chunk", {"audio": audio}, to=sid)


def _check_notice(sid: str, intent: str, user_text: str):
    """If a topic appears ≥4 times in the last 20 logged questions, send a one-off daily notice."""
    from collections import Counter
    try:
        with _db.get_db_conn() as conn:
            row = conn.execute("SELECT question_log FROM patterns WHERE id=1").fetchone()
        if not row:
            return
        log = json.loads(row["question_log"] or "[]")
        recent = log[-20:]
        if len(recent) < 4:
            return
        counts = Counter(e["intent"] for e in recent if e.get("intent"))
        topic, freq = counts.most_common(1)[0] if counts else (None, 0)
        if not topic or freq < 4:
            return

        person = _connected_known.get(sid, "unknown")
        today  = _dt.utcnow().strftime("%Y-%m-%d")
        with _db.get_db_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM notices WHERE person=? AND topic=? AND sent_at >= ?",
                (person, topic, today + "T00:00:00")
            ).fetchone()
        if existing:
            return

        notice = f"You've been asking a lot about {topic.replace('_', ' ')} today — want me to add it to your morning brief?"
        socketio.emit("proactive_brief", {"text": notice}, to=sid)

        with _db.get_db_conn() as conn:
            conn.execute(
                "INSERT INTO notices (person, topic, sent_at) VALUES (?, ?, ?)",
                (person, topic, _dt.utcnow().isoformat())
            )
            conn.commit()
    except Exception:
        pass


try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(_scheduled_morning_brief, "cron", day_of_week="mon-fri", hour=7, minute=0)
    _scheduler.add_job(_scheduled_market_monitor, "interval", hours=2)
    _scheduler.add_job(_scheduled_eod_summary, "cron", hour=17, minute=0)
    _scheduler.start()
    atexit.register(_scheduler.shutdown)
    print("[Scheduler] Started — morning brief 07:00 UTC, monitor 2h, EOD 17:00 UTC")
except Exception as _sched_err:
    print(f"[Scheduler] Could not start: {_sched_err}")


# ── OAuth routes ──────────────────────────────────────────────

@app.route("/auth/google")
def auth_google():
    person = request.args.get("person", "favour").lower()
    if not os.getenv("GOOGLE_CLIENT_ID"):
        return "Google OAuth not configured — set GOOGLE_CLIENT_ID in .env", 400
    flow = _google_flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent",
                                         state=person, include_granted_scopes="true")
    return redirect(url)


@app.route("/auth/google/callback")
def auth_google_callback():
    person = request.args.get("state", "favour").lower()
    try:
        flow = _google_flow()
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        with _db.get_db_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO calendar_tokens (person, access_token, refresh_token, expiry, scopes)
                VALUES (?, ?, ?, ?, ?)
            """, (person, creds.token, creds.refresh_token, str(creds.expiry),
                  " ".join(creds.scopes or [])))
            conn.commit()
        return f"Calendar connected for {person}. You can close this tab."
    except Exception as e:
        return f"OAuth error: {e}", 400


# Stores names for guests mid-greeting flow: sid → entered name
_pending_greeting: dict = {}


@app.route("/")
def index():
    startup_context = request.args.get("context","").strip()[:2000]
    return render_template("index.html", startup_context=startup_context)


@socketio.on("connect")
def on_connect():
    sid = request.sid
    if FYRA_TOKEN and request.args.get("token", "") != FYRA_TOKEN:
        return False  # reject unauthorised connection

    profile_data = memory_module.get_profile_panel_data()
    socketio.emit("profile_update", profile_data, to=sid)

    history = memory_module.load_conversation_history(limit=20)
    if history:
        socketio.emit("conversation_history", {"history": history}, to=sid)

    # If client already knows who they are (reconnect), skip the name prompt
    known_person = request.args.get("person", "").strip().lower()
    if known_person in ("favour", "fiyin"):
        threading.Thread(
            target=_emit_greeting,
            args=(sid, "Mr. Favour" if known_person == "favour" else "Miss Fiyin", known_person),
            daemon=True,
        ).start()
        return

    prompt = "Who am I speaking with?"
    audio = _tts(prompt)
    socketio.emit("greeting_prompt", {"text": prompt, "audio": audio}, to=sid)


def _emit_greeting(sid: str, addressed_name: str, memory_key: str):
    ctx = memory_module.get_relevant_memory("check_in", memory_key)
    if memory_key in ("favour", "fiyin"):
        calendar_ctx = get_upcoming_events(memory_key)
        if calendar_ctx:
            ctx = ctx + "\n\n" + calendar_ctx
    greeting = _generate_greeting(addressed_name, ctx)
    socketio.emit("stream_start", {}, to=sid)
    socketio.emit("stream_chunk", {"text": greeting}, to=sid)
    end_payload = {"intent": "greeting"}
    if memory_key in ("favour", "fiyin"):
        end_payload["person"] = memory_key
    socketio.emit("stream_end", end_payload, to=sid)
    audio = _tts(greeting)
    if audio:
        socketio.emit("audio_chunk", {"audio": audio}, to=sid)
    if memory_key in ("favour", "fiyin"):
        _connected_known[sid] = memory_key


@socketio.on("greeting_response")
def handle_greeting(data):
    text = data.get("text", "").strip()
    sid = request.sid
    lower = text.lower()

    if "favour" in lower:
        _emit_greeting(sid, "Mr. Favour", "favour")
    elif "fiyin" in lower:
        _emit_greeting(sid, "Miss Fiyin", "fiyin")
    else:
        # Unknown guest — store name and ask gender
        entered_name = text.strip().split()[0].capitalize() or "there"
        _pending_greeting[sid] = entered_name
        question = "Are you male or female?"
        audio = _tts(question)
        socketio.emit("greeting_ask_gender", {"text": question, "audio": audio}, to=sid)


@socketio.on("greeting_gender")
def handle_greeting_gender(data):
    text = data.get("text", "").strip().lower()
    sid = request.sid
    entered_name = _pending_greeting.pop(sid, "there")
    prefix = "Mr." if any(w in text for w in ("male", "man", "mr", "boy")) else "Miss"
    addressed_name = f"{prefix} {entered_name}"
    _emit_greeting(sid, addressed_name, "general_chat")


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    _pending_greeting.pop(sid, None)
    _connected_known.pop(sid, None)
    _pending_charts.pop(sid, None)
    assistant.clear_session(sid)


@socketio.on("user_message")
def handle_message(data):
    text = data.get("text", "").strip()
    if not text:
        return

    sid = request.sid

    try:
        _db.check_budget()
    except BudgetExceeded as e:
        socketio.emit("stream_start", {}, to=sid)
        socketio.emit("stream_chunk", {"text": str(e)}, to=sid)
        socketio.emit("stream_end", {"intent": "error"}, to=sid)
        audio = _tts(str(e))
        if audio:
            socketio.emit("audio_chunk", {"audio": audio}, to=sid)
        return

    socketio.emit("status", {"state": "processing"}, to=sid)

    classified_intent = intent_module.classify(text, _client)
    # Large pastes are treated as filing/document interpretation
    if len(text) > 500 and classified_intent == "general_chat":
        classified_intent = "filing_query"
    ctx = memory_module.get_relevant_memory(classified_intent, text)
    if classified_intent == "task_help":
        person = _connected_known.get(sid)
        if person:
            cal_ctx = get_upcoming_events(person)
            if cal_ctx:
                ctx = ctx + "\n\n" + cal_ctx
    learning = memory_module.get_learning_context()
    if learning:
        ctx = ctx + "\n\n" + learning

    full_response = ""
    sentence_buf = ""
    socketio.emit("stream_start", {}, to=sid)

    def _on_tool(name, _inp):
        socketio.emit("tool_use", {"tool": name}, to=sid)

    # Background TTS thread — converts sentences to audio as they stream in,
    # so speech starts while the rest of the text is still appearing.
    tts_q = queue.SimpleQueue()

    def _tts_worker():
        while True:
            item = tts_q.get()
            if item is None:
                break
            audio = _tts(item)
            if audio:
                socketio.emit("audio_chunk", {"audio": audio}, to=sid)

    tts_thread = threading.Thread(target=_tts_worker, daemon=True)
    tts_thread.start()

    for chunk in assistant.respond_stream(text, ctx, _client, sid, on_tool_call=_on_tool):
        full_response += chunk
        sentence_buf += chunk
        socketio.emit("stream_chunk", {"text": chunk}, to=sid)

        stripped = sentence_buf.strip()
        if stripped and stripped[-1] in ".!?:" and len(stripped) >= 12:
            tts_q.put(_strip_md(stripped))
            sentence_buf = ""

    if sentence_buf.strip():
        tts_q.put(_strip_md(sentence_buf.strip()))
    tts_q.put(None)  # signal worker to stop

    socketio.emit("stream_end", {"intent": classified_intent}, to=sid)

    memory_module.log_question_pattern(classified_intent, text, _client)
    _check_notice(sid, classified_intent, text)

    if classified_intent == "correction":
        memory_module.save_correction(text, full_response, _client)
    elif classified_intent in ("store_memory", "check_in", "task_help"):
        extracted = assistant.extract_memory_update(
            text, classified_intent, full_response, _client
        )
        memory_module.apply_memory_update(extracted)

    memory_module.save_conversation_turn(text, full_response)
    memory_module.log_interaction(text, classified_intent, full_response)

    # Pre-build chart in background and offer it; only emit when user requests
    if classified_intent in ("market_query", "filing_query"):
        _query_text = text
        def _prebuild_chart():
            dataset = _pick_chart_dataset(_query_text)
            raw = fetch_afriterminal_data(dataset)
            if "[FAILED]" not in raw:
                charts = _build_chart_data(dataset, raw)
                if charts:
                    _pending_charts[sid] = charts
                    socketio.emit("chart_offer", {}, to=sid)
        threading.Thread(target=_prebuild_chart, daemon=True).start()

    profile_data = memory_module.get_profile_panel_data()
    socketio.emit("profile_update", profile_data, to=sid)


@socketio.on("request_chart")
def handle_request_chart(_data=None):
    sid = request.sid
    charts = _pending_charts.pop(sid, None)
    if charts:
        socketio.emit("chart_data", {"charts": charts}, to=sid)


@socketio.on("voice_sample")
def handle_voice_sample(data):
    """Receive acoustic feature sample from browser; match or store."""
    sid     = request.sid
    avg_rms = float(data.get("avg_rms", 0))
    if avg_rms <= 0:
        return

    # Load existing voice profiles
    with _db.get_db_conn() as conn:
        profiles = conn.execute(
            "SELECT person, avg_rms, sample_count FROM voice_profiles"
        ).fetchall()

    best_match = None
    best_dist  = float("inf")
    for p in profiles:
        if not p["avg_rms"] or p["sample_count"] < 3:
            continue
        dist = abs(avg_rms - p["avg_rms"])
        # Relative distance — must be within 25%
        if p["avg_rms"] > 0 and dist / p["avg_rms"] < 0.25 and dist < best_dist:
            best_dist  = dist
            best_match = p["person"]

    if best_match:
        # High confidence match — skip name prompt
        socketio.emit("voice_id_result", {"matched": True, "person": best_match}, to=sid)
        # Update running average
        for p in profiles:
            if p["person"] == best_match:
                n   = p["sample_count"]
                new_avg = (p["avg_rms"] * n + avg_rms) / (n + 1)
                with _db.get_db_conn() as conn:
                    conn.execute(
                        "UPDATE voice_profiles SET avg_rms=?, sample_count=? WHERE person=?",
                        (new_avg, n + 1, best_match)
                    )
                    conn.commit()
    else:
        # No match — server waits; client will fall through to name prompt
        # Store this sample temporarily keyed by sid for learning after greeting
        socketio.emit("voice_id_result", {"matched": False}, to=sid)
        # Persist the RMS against the session's person once identified (via voice_learn_confirm)
        _pending_voice[sid] = avg_rms


_pending_voice: dict = {}  # sid → avg_rms collected before identity confirmed


@socketio.on("voice_learn_confirm")
def handle_voice_learn_confirm(data):
    """After greeting completes, attribute the pre-collected voice sample to the person."""
    sid    = request.sid
    person = data.get("person", "").lower()
    if person not in ("favour", "fiyin"):
        return
    avg_rms = _pending_voice.pop(sid, None)
    if avg_rms is None:
        return
    with _db.get_db_conn() as conn:
        existing = conn.execute(
            "SELECT avg_rms, sample_count FROM voice_profiles WHERE person=?", (person,)
        ).fetchone()
    if existing and existing["sample_count"]:
        n = existing["sample_count"]
        new_avg = (existing["avg_rms"] * n + avg_rms) / (n + 1)
        with _db.get_db_conn() as conn:
            conn.execute(
                "UPDATE voice_profiles SET avg_rms=?, sample_count=? WHERE person=?",
                (new_avg, n + 1, person)
            )
            conn.commit()
    else:
        with _db.get_db_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO voice_profiles (person, avg_rms, pitch_mean, pitch_std, sample_count) VALUES (?, ?, NULL, NULL, 1)",
                (person, avg_rms)
            )
            conn.commit()
    socketio.emit("voice_learn", {}, to=sid)


@socketio.on("set_voice")
def handle_set_voice(data):
    """Allow setting voice ID from the UI at runtime."""
    voice_id = data.get("voice_id", "").strip()
    os.environ["FISH_AUDIO_VOICE_ID"] = voice_id
    emit("voice_set", {"voice_id": voice_id})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    ip = _local_ip()
    print(f"\nFyra UI → http://localhost:{port}")
    print(f"Mobile  → http://{ip}:{port}\n")
    socketio.run(app, host="0.0.0.0", debug=False, port=port, allow_unsafe_werkzeug=True)
