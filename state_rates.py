"""
All-India state gold rates with a fallback chain per state.

Each state lists its sources in priority order. Official association boards
come first where one exists; everywhere else goodreturns, then Groww (same
page template), then Kalyan's own board as an independent last resort.

A source is used only when:
  - it parsed a 22K per-gram rate,
  - its page date is today (IST),
  - 18K < 22K < 24K when those are present,
  - 22K is within MAX_DEVIATION of the median of every fresh rate seen this run.
If no source in the chain passes, the freshest valid reading is kept and marked
stale; if nothing was readable at all, the previous saved value is kept.

Writes state_rates.json. Returns True when any state's rate changed.
"""

import json
import os
import re
import statistics
import time
from datetime import datetime, timedelta
from html import unescape

import pytz
import requests

IST = pytz.timezone("Asia/Kolkata")
OUTPUT_FILE = "state_rates.json"
HISTORY_FILE = "state_rates_history.json"
HISTORY_DAYS = 45
MAX_DEVIATION = 0.03
MAX_DAILY_MOVE = 0.08  # vs the last saved value; gold has not moved 8% in a day
REQUEST_GAP_SECONDS = 0.5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# ============================================================================
# STATE → SOURCE CHAIN
# ============================================================================

def gr(city):
    return ("goodreturns", city)


def gw(city):
    return ("groww", city)


KALYAN = ("kalyan", "chennai")


def market(city):
    """Fallback chain for states with no association board online."""
    return [gr(city), gw(city), KALYAN]


STATES = [
    # id, name, official, chain
    ("kerala", "Kerala", True, [("akgsma", None), gr("kochi"), gw("kochi"), KALYAN]),
    ("lakshadweep", "Lakshadweep", True, [("akgsma", None), gr("kochi"), gw("kochi")]),
    ("tamil-nadu", "Tamil Nadu", True, [("cwja", None), ("cja", None), gr("chennai"), gw("chennai")]),
    ("puducherry", "Puducherry", True, [("cwja", None), gr("chennai"), gw("chennai")]),
    ("andaman-nicobar", "Andaman & Nicobar", True, [("cwja", None), gr("chennai"), gw("chennai")]),
    ("karnataka", "Karnataka", True, [("ksjf", None), gr("bangalore"), gw("bangalore"), KALYAN]),
    ("telangana", "Telangana", False, market("hyderabad")),
    ("andhra-pradesh", "Andhra Pradesh", False, market("vijayawada")),
    ("maharashtra", "Maharashtra", False, market("mumbai")),
    ("goa", "Goa", False, market("mumbai")),
    ("gujarat", "Gujarat", False, market("ahmedabad")),
    ("dnh-dd", "Dadra Nagar Haveli & Daman Diu", False, market("surat")),
    ("rajasthan", "Rajasthan", False, market("jaipur")),
    ("madhya-pradesh", "Madhya Pradesh", False, market("indore")),
    ("chhattisgarh", "Chhattisgarh", False, market("raipur")),
    ("delhi", "Delhi", False, market("delhi")),
    ("uttar-pradesh", "Uttar Pradesh", False, market("lucknow")),
    ("uttarakhand", "Uttarakhand", False, market("lucknow")),
    ("punjab", "Punjab", False, market("chandigarh")),
    ("haryana", "Haryana", False, market("chandigarh")),
    ("chandigarh", "Chandigarh", False, market("chandigarh")),
    ("himachal-pradesh", "Himachal Pradesh", False, market("chandigarh")),
    ("jammu-kashmir", "Jammu & Kashmir", False, market("delhi")),
    ("ladakh", "Ladakh", False, market("delhi")),
    ("bihar", "Bihar", False, market("patna")),
    ("jharkhand", "Jharkhand", False, market("patna")),
    ("west-bengal", "West Bengal", False, market("kolkata")),
    ("odisha", "Odisha", False, market("bhubaneswar")),
    ("assam", "Assam", False, market("guwahati")),
    ("north-east", "Arunachal, Manipur, Meghalaya, Mizoram, Nagaland, Sikkim, Tripura",
     False, market("guwahati")),
]

SOURCE_LABELS = {
    "akgsma": "AKGSMA (Kerala board)",
    "cwja": "CWJA (Chennai board)",
    "cja": "Coimbatore Jewellers Assn",
    "ksjf": "KSJF (Karnataka board)",
    "goodreturns": "Goodreturns",
    "groww": "Groww",
    "kalyan": "Kalyan Jewellers",
}

OFFICIAL_SOURCES = {"akgsma", "cwja", "cja", "ksjf"}


# ============================================================================
# HELPERS
# ============================================================================

def log(message, source="STATES"):
    timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"[{timestamp}] [{source}] {message}")


def today_ist():
    return datetime.now(IST).date()


def to_int(value):
    if value is None:
        return None
    try:
        return int(round(float(str(value).replace(",", "").strip())))
    except Exception:
        return None


def page_text(html):
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html)))


def iso(d):
    return d.isoformat() if d else None


def date_from_dmy(day, month, year):
    try:
        month_num = int(month) if str(month).isdigit() else MONTHS[str(month)[:3].lower()]
        return datetime(int(year), month_num, int(day)).date()
    except Exception:
        return None


def fetch_html(url):
    for attempt in range(2):
        try:
            res = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en-IN,en;q=0.9"},
                timeout=15,
            )
            if res.status_code == 200:
                res.encoding = res.encoding or "utf-8"
                return res.text
            log(f"HTTP {res.status_code} for {url}")
        except Exception as e:
            log(f"Fetch error for {url}: {str(e)[:80]}")
        time.sleep(1 + attempt)
    return None


# ============================================================================
# PARSERS — each returns {"date", "rate22k", "rate18k", "rate24k", "silver"} or None
# ============================================================================

def parse_cwja(html):
    t = page_text(html)
    g22 = re.search(r"Gold 22Kt \(₹\)\s*([\d,]+)", t)
    if not g22:
        return None
    g18 = re.search(r"Gold 18Kt \(₹\)\s*([\d,]+)", t)
    silver = re.search(r"1 Gm Silver \(₹\)\s*([\d,.]+)", t)
    d = re.search(r"Update Time\s*:\s*(\d{2})-(\d{2})-(\d{4})", t)
    return {
        "date": date_from_dmy(*d.groups()) if d else None,
        "rate22k": to_int(g22.group(1)),
        "rate18k": to_int(g18.group(1)) if g18 else None,
        "rate24k": None,
        "silver": to_int(silver.group(1)) if silver else None,
    }


def parse_cja(html):
    t = page_text(html)
    g22 = re.search(r"22kT Gold Rate\W*₹\s*([\d,]+)", t)
    if not g22:
        return None
    g18 = re.search(r"18kT Gold Rate\W*₹\s*([\d,]+)", t)
    silver = re.search(r"Silver Rate\W*₹\s*([\d,.]+)", t)
    d = re.search(r"Update Time:\s*(\d{4})\.(\d{2})\.(\d{2})", t)
    return {
        "date": date_from_dmy(d.group(3), d.group(2), d.group(1)) if d else None,
        "rate22k": to_int(g22.group(1)),
        "rate18k": to_int(g18.group(1)) if g18 else None,
        "rate24k": None,
        "silver": to_int(silver.group(1)) if silver else None,
    }


def parse_ksjf(html):
    t = page_text(html)
    g22 = re.search(r"Gold 22CT Rs\s*([\d,]+)\s*/\s*1 GRM", t)
    if not g22:
        return None
    g24 = re.search(r"Gold 24CT Rs\s*([\d,]+)\s*/\s*1 GRM", t)
    silver_kg = re.search(r"Silver Rs\s*([\d,]+)\s*/\s*1 KG", t)
    d = re.search(r"Updated (\d{1,2}) (\w{3,9}) (\d{4})", t)
    return {
        "date": date_from_dmy(*d.groups()) if d else None,
        "rate22k": to_int(g22.group(1)),
        "rate18k": None,
        "rate24k": to_int(g24.group(1)) if g24 else None,
        "silver": round(to_int(silver_kg.group(1)) / 1000) if silver_kg else None,
    }


def parse_rate_sentence(html, date_pattern):
    """Goodreturns and Groww share one sentence: '₹X per gram for 24 karat gold ...'."""
    t = page_text(html)
    g22 = re.search(r"₹\s?([\d,]+(?:\.\d+)?) per gram for 22 karat", t)
    if not g22:
        return None
    g24 = re.search(r"₹\s?([\d,]+(?:\.\d+)?) per gram for 24 karat", t)
    g18 = re.search(r"₹\s?([\d,]+(?:\.\d+)?) per gram for 18 karat", t)
    d = re.search(date_pattern, html)
    return {
        "date": date_from_dmy(*d.groups()) if d else None,
        "rate22k": to_int(g22.group(1)),
        "rate18k": to_int(g18.group(1)) if g18 else None,
        "rate24k": to_int(g24.group(1)) if g24 else None,
        "silver": None,  # their silver pages lag; not used
    }


def parse_goodreturns(html):
    return parse_rate_sentence(html, r"<title>[^<]*? on (\d{1,2}) (\w+) (\d{4})")


def parse_groww(html):
    return parse_rate_sentence(html, r"Last updated:\s*(?:<!-- -->)?\s*(\d{1,2}) (\w{3}) (\d{4})")


def parse_kalyan(html):
    """Kalyan quotes per 10g: '₹ 130900 10g of 22K Gold'."""
    t = page_text(html)
    g22 = re.search(r"₹\s*([\d,]+) 10g of 22K", t)
    if not g22:
        return None
    g24 = re.search(r"₹\s*([\d,]+) 10g of 24K", t)
    g18 = re.search(r"\b18k ₹\s*([\d,]+)", t)
    d = re.search(r"Updated on \w+, (\d{1,2})(?:st|nd|rd|th) (\w+) (\d{4})", t)
    return {
        "date": date_from_dmy(*d.groups()) if d else None,
        "rate22k": round(to_int(g22.group(1)) / 10),
        "rate18k": round(to_int(g18.group(1)) / 10) if g18 else None,
        "rate24k": round(to_int(g24.group(1)) / 10) if g24 else None,
        "silver": None,
    }


SOURCE_URLS = {
    "cwja": lambda city: "https://cwja.org.in/",
    "cja": lambda city: "https://coimbatorejewellery.org/",
    "ksjf": lambda city: "https://ksjf.in/",
    "goodreturns": lambda city: f"https://www.goodreturns.in/gold-rates/{city}.html",
    "groww": lambda city: f"https://groww.in/gold-rates/gold-rate-today-in-{city}",
    "kalyan": lambda city: f"https://store.kalyanjewellers.net/gold-rate/{city}/en",
}

PARSERS = {
    "cwja": parse_cwja,
    "cja": parse_cja,
    "ksjf": parse_ksjf,
    "goodreturns": parse_goodreturns,
    "groww": parse_groww,
    "kalyan": parse_kalyan,
}


# ============================================================================
# FETCHING (cached per run, lazy)
# ============================================================================

class SourceReader:
    def __init__(self, akgsma_rates):
        self.cache = {}
        self.akgsma_rates = akgsma_rates or {}

    def url(self, key, city):
        if key == "akgsma":
            return "http://akgsma.com/index.php"
        return SOURCE_URLS[key](city)

    def read(self, key, city):
        cache_key = (key, city)
        if cache_key in self.cache:
            return self.cache[cache_key]

        if key == "akgsma":
            reading = self._from_akgsma()
        else:
            html = fetch_html(self.url(key, city))
            time.sleep(REQUEST_GAP_SECONDS)
            reading = None
            if html:
                try:
                    reading = PARSERS[key](html)
                except Exception as e:
                    log(f"Parse error {key}/{city}: {str(e)[:80]}")
            if reading is None and html:
                log(f"No rate found on {key}/{city}")

        self.cache[cache_key] = reading
        return reading

    def _from_akgsma(self):
        """Reuse this run's AKGSMA reading instead of fetching it twice."""
        r = self.akgsma_rates
        rate22k = to_int(r.get("22K916"))
        if not rate22k:
            return None
        d = re.match(r"(\d{2})/(\d{2})/(\d{4})", r.get("date") or "")
        return {
            "date": date_from_dmy(*d.groups()) if d else None,
            "rate22k": rate22k,
            "rate18k": to_int(r.get("18K750")),
            "rate24k": None,
            "silver": to_int(r.get("Silver")),
        }


# ============================================================================
# VALIDATION + SELECTION
# ============================================================================

def is_well_formed(reading):
    if not reading or not reading.get("rate22k"):
        return False
    g22 = reading["rate22k"]
    if not 3_000 <= g22 <= 100_000:
        return False
    if reading.get("rate18k") and not reading["rate18k"] < g22:
        return False
    if reading.get("rate24k") and not reading["rate24k"] > g22:
        return False
    return True


def within_band(reading, median):
    if median is None:
        return True
    return abs(reading["rate22k"] - median) / median <= MAX_DEVIATION


def plausible_move(reading, previous_rate):
    if not previous_rate:
        return True
    return abs(reading["rate22k"] - previous_rate) / previous_rate <= MAX_DAILY_MOVE


def select_rate(chain, reader, median, today, previous_rate=None):
    """Walk the chain; return (source_key, city, reading, stale)."""
    fallback = None
    for key, city in chain:
        reading = reader.read(key, city)
        if not is_well_formed(reading):
            continue
        if not within_band(reading, median):
            log(f"{key}/{city} 22K {reading['rate22k']} is >{int(MAX_DEVIATION * 100)}% "
                f"from median {median}, skipped")
            continue
        if not plausible_move(reading, previous_rate):
            log(f"{key}/{city} 22K {reading['rate22k']} moved >{int(MAX_DAILY_MOVE * 100)}% "
                f"from last saved {previous_rate}, skipped")
            continue
        if reading.get("date") == today:
            return key, city, reading, False
        if fallback is None or (reading.get("date") or datetime.min.date()) > (
                fallback[2].get("date") or datetime.min.date()):
            fallback = (key, city, reading)
    if fallback:
        return (*fallback, True)
    return None


def load_previous():
    if not os.path.exists(OUTPUT_FILE):
        return {}
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("states", {})
    except Exception as e:
        log(f"Could not read {OUTPUT_FILE}: {e}")
        return {}


RATE_FIELDS = ["rate22k", "rate18k", "rate24k", "silver", "date", "source", "stale"]

# States whose 22K moved to a fresh, today-dated value in the last run(). The workflow sends
# these to the webapp, which makes Starter shops' posters for them right away.
RATE_CHANGES = []


def update_history(states, today_iso, now):
    """Keep the last fresh, today-dated reading per state per day (HISTORY_DAYS days).

    Shape: {"updated": "...", "days": {"2026-11-05": {"kerala": {"rate22k": ..,
    "rate18k": .., "rate24k": .., "silver": .., "source": .., "at": "09:25"}}}}
    Only readings dated today and not stale are recorded, so a day without a
    new rate simply has no entry for that state.
    """
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        days = data.get("days", {}) if isinstance(data, dict) else {}
    except Exception:
        days = {}
    day = days.setdefault(today_iso, {})
    changed = False
    for state_id, e in states.items():
        if e.get("stale") or e.get("date") != today_iso or not e.get("rate22k"):
            continue
        row = {
            "rate22k": e["rate22k"],
            "rate18k": e.get("rate18k"),
            "rate24k": e.get("rate24k"),
            "silver": e.get("silver"),
            "source": e.get("source"),
            "at": str(e.get("last_changed") or now)[11:16],
        }
        old = day.get(state_id)
        if not old or any(old.get(k) != row[k] for k in ("rate22k", "rate18k", "rate24k", "silver", "source")):
            day[state_id] = row
            changed = True
    keep = sorted(days)[-HISTORY_DAYS:]
    if len(keep) != len(days):
        changed = True
    days = {d: days[d] for d in keep if days[d]}
    if changed or not os.path.exists(HISTORY_FILE):
        tmp = HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"updated": now, "days": days}, f, indent=1, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, HISTORY_FILE)
        log(f"Wrote {HISTORY_FILE} ({len(days)} days)")
    return changed


def run(akgsma_rates=None):
    """Fetch every state's rate, write state_rates.json, return True if anything changed."""
    today = today_ist()
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    reader = SourceReader(akgsma_rates)
    RATE_CHANGES.clear()
    previous = load_previous()

    # Pass 1: read every primary so the median reflects the whole market.
    # If too few are fresh (a feed is down), read the first backups as well.
    def fresh_rates():
        return [r["rate22k"] for r in reader.cache.values()
                if is_well_formed(r) and r.get("date") == today]

    for _, _, _, chain in STATES:
        reader.read(*chain[0])
    if len(fresh_rates()) < 3:
        for _, _, _, chain in STATES:
            if len(chain) > 1:
                reader.read(*chain[1])
    fresh = fresh_rates()
    median = statistics.median(fresh) if len(fresh) >= 3 else None
    log(f"{len(fresh)} fresh readings, 22K median {median}")

    # Pass 2: pick per state, falling back lazily.
    states = {}
    changed = False
    for state_id, name, official_state, chain in STATES:
        prev = previous.get(state_id, {})
        picked = select_rate(chain, reader, median, today, prev.get("rate22k"))

        if picked:
            key, city, reading, stale = picked
            entry = {
                "name": name,
                "rate22k": reading["rate22k"],
                "rate18k": reading.get("rate18k"),
                "rate24k": reading.get("rate24k"),
                "rate22k_8g": reading["rate22k"] * 8,
                "silver": reading.get("silver"),
                "date": iso(reading.get("date")),
                "source": key,
                "source_label": SOURCE_LABELS[key],
                "source_url": reader.url(key, city),
                "official": key in OFFICIAL_SOURCES,
                "stale": stale,
            }
        elif prev:
            log(f"{name}: no source readable, keeping previous value")
            entry = dict(prev, stale=True)
        else:
            log(f"{name}: no source readable and no previous value")
            continue

        if any(entry.get(f) != prev.get(f) for f in RATE_FIELDS):
            changed = True
            entry["last_changed"] = now
            if prev.get("rate22k") != entry["rate22k"]:
                log(f"{name}: 22K {prev.get('rate22k')} -> {entry['rate22k']} via {entry['source']}")
                if not entry.get("stale") and entry.get("date") == iso(today):
                    RATE_CHANGES.append(state_id)
        else:
            entry["last_changed"] = prev.get("last_changed", now)

        if entry["source"] != chain[0][0] and not entry.get("stale"):
            log(f"{name}: primary {chain[0][0]} unusable, using backup {entry['source']}")
        states[state_id] = entry

    if changed or not os.path.exists(OUTPUT_FILE):
        tmp = OUTPUT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"last_changed": now, "states": states}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, OUTPUT_FILE)
        log(f"Wrote {OUTPUT_FILE} ({len(states)} states)")
    else:
        log("No state rate changes")

    try:
        if update_history(states, iso(today), now):
            changed = True
    except Exception as e:
        log(f"Could not update {HISTORY_FILE}: {e}")

    return changed


if __name__ == "__main__":
    try:
        with open("akgsma_rates_history.json", "r", encoding="utf-8") as f:
            saved_akgsma = json.load(f).get("last_rates", {})
    except Exception:
        saved_akgsma = {}
    run(saved_akgsma)
