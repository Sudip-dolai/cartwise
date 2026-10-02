import asyncio, base64, smtplib, hashlib, hmac, json, math, os, re, secrets, time
from pathlib import Path
from typing import Any, Optional

import httpx
from collections import Counter
from email.message import EmailMessage
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()
FRONT = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Cartwise API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- demo catalog (used when QuickCommerce keys are missing or a call fails) ----------
DEMO = [
    ("boAt Airdopes 141", "boAt", "earbuds", 1299, 4490, 4.1, 412000, "Blinkit",
     ["42h playback", "ENx noise reduction", "Bluetooth 5.3", "IPX4"],
     ["Battery easily lasts two days.", "Mic is average on calls but bass is great for the price.", "Case feels plasticky."]),
    ("Noise Buds VS104", "Noise", "earbuds", 999, 3499, 3.9, 98000, "Zepto",
     ["45h playback", "Quad mic ENC", "Bluetooth 5.2", "IPX5"],
     ["Good value, comfortable fit.", "Connection drops sometimes.", "Sound is decent, not amazing."]),
    ("OnePlus Nord Buds 2r", "OnePlus", "earbuds", 1799, 2999, 4.2, 56000, "Blinkit",
     ["38h playback", "12.4mm drivers", "Bluetooth 5.3", "IP55"],
     ["Best sound at this price, clear vocals.", "Fit is secure for workouts.", "Case is bulky."]),
    ("Noise ColorFit Pulse 3", "Noise", "smartwatch", 1999, 5999, 4.0, 74000, "Swiggy Instamart",
     ["1.96in AMOLED", "Bluetooth calling", "7 day battery", "100+ sports modes"],
     ["Bright display, calling works well.", "Step tracking is slightly off.", "Strap is comfortable."]),
    ("boAt Wave Call 2", "boAt", "smartwatch", 1499, 6999, 3.8, 132000, "Zepto",
     ["1.83in HD", "Bluetooth calling", "10 day battery", "IP68"],
     ["Battery is superb.", "Display is dim in sunlight.", "App sync is slow and buggy."]),
    ("Fire-Boltt Ninja Call Pro", "Fire-Boltt", "smartwatch", 1299, 8999, 3.7, 210000, "Blinkit",
     ["1.83in display", "Bluetooth calling", "AI voice assistant", "120 sports modes"],
     ["Looks premium for the price.", "Stopped working after two months.", "Calling quality is poor."]),
]

def demo_products(q: str):
    toks = [t for t in re.findall(r"[a-z0-9]+", q.lower()) if len(t) > 1]
    out = []
    for i, d in enumerate(DEMO):
        hay = f"{d[0]} {d[1]} {d[2]}".lower()
        if not toks or any(t in hay or hay.find(t.rstrip('s')) >= 0 for t in toks):
            out.append(make(i, d))
    return out or [make(i, d) for i, d in enumerate(DEMO)]

def make(i, d):
    name, brand, cat, price, mrp, rating, n, platform, feats, revs = d
    return {"id": f"demo-{i}", "name": name, "brand": brand, "category": cat, "price": price, "mrp": mrp,
            "discount": round((mrp - price) / mrp * 100), "rating": rating, "reviews_count": n,
            "platform": platform, "image": "", "features": feats, "reviews": revs}

# ---------- helpers ----------
def num(v, default=0.0):
    try:
        s = re.sub(r"[^\d.]", "", str(v))
        return float(s) if s else default
    except Exception:
        return default

def pick(d: dict, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return default

def normalize(raw: dict, i: int, platform_hint: str = "") -> dict:
    price = num(pick(raw, "offer_price", "price", "selling_price", "sp", "sale_price"))
    mrp = num(pick(raw, "mrp", "original_price", "list_price", "market_price"), price) or price
    plat = raw.get("platform")
    sla = ""
    if isinstance(plat, dict):
        sla = str(plat.get("sla") or "")
        plat = plat.get("name")
    plat = str(plat or platform_hint or "")
    feats = pick(raw, "features", "highlights", "attributes", default=[])
    if isinstance(feats, str):
        feats = [x.strip() for x in re.split(r"[;\n|]", feats) if x.strip()]
    if isinstance(feats, dict):
        feats = [f"{k}: {v}" for k, v in feats.items()]
    feats = [str(f) for f in feats]
    if raw.get("quantity"):
        feats.insert(0, str(raw["quantity"]))
    if sla:
        feats.append(f"Delivery in {sla}")
    revs = pick(raw, "reviews", "top_reviews", default=[])
    revs = [r if isinstance(r, str) else str(pick(r, "text", "comment", "review", default="")) for r in revs] if isinstance(revs, list) else []
    imgs = raw.get("images")
    img = imgs[0] if isinstance(imgs, list) and imgs else pick(raw, "image", "image_url", "thumbnail", "img", default="")
    rid = str(pick(raw, "id", "product_id", "sku", "slug", default=f"p-{i}"))
    return {
        "id": f"{plat}-{rid}" if plat else rid,
        "name": str(pick(raw, "name", "title", "product_name", default="Unnamed product")),
        "brand": str(pick(raw, "brand", "manufacturer", default="") or ""),
        "category": str(pick(raw, "category", default="")),
        "price": price, "mrp": mrp,
        "discount": round((mrp - price) / mrp * 100) if mrp and mrp > price else 0,
        "rating": min(5.0, num(pick(raw, "rating", "avg_rating", "stars"))),
        "reviews_count": int(num(pick(raw, "rating_count", "ratingCount", "reviews_count", "review_count", "num_reviews"))),
        "platform": {"swiggy": "Instamart", "minutes": "Flipkart Minutes", "blinkit": "Blinkit", "jiomart": "JioMart"}.get(plat.lower(), plat),
        "eta": int(num(sla)) if sla else 0, "image": str(img or ""), "link": str(raw.get("deeplink") or ""),
        "features": feats[:8], "reviews": revs[:10],
    }

def parse_results(data: Any) -> list:
    """Handles QuickCommerceAPI groupsearch ({data:{results:{Platform:[...]}}}) and generic lists."""
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if isinstance(data, dict) and isinstance(data.get("results"), dict):
        out = []
        for plat, items in data["results"].items():
            good = [x for x in (items or []) if isinstance(x, dict) and x.get("available", True)]
            out += [normalize(x, i, plat) for i, x in enumerate(good[:8])]
        return out
    if isinstance(data, dict):
        data = next((data[k] for k in ("products", "results", "items", "data") if isinstance(data.get(k), list)), [])
    return [normalize(x, i) for i, x in enumerate(data or []) if isinstance(x, dict)]

GEO: dict[str, tuple] = {}

async def geocode(pin: str) -> Optional[tuple]:
    """Pincode -> (lat, lon) using OpenStreetMap Nominatim, cached."""
    if pin in GEO:
        return GEO[pin]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://nominatim.openstreetmap.org/search",
                            params={"postalcode": pin, "country": "India", "format": "json", "limit": 1},
                            headers={"User-Agent": "Cartwise/1.0"})
            r.raise_for_status()
            d = r.json()
        if d:
            GEO[pin] = (float(d[0]["lat"]), float(d[0]["lon"]))
            return GEO[pin]
    except Exception:
        pass
    return None

async def fetch_quickcommerce(q: str, pincode: str = "", platforms: str = ""):
    """Returns (items, error_message). Retries on timeouts / 429 / 5xx with backoff."""
    key = os.getenv("QC_API_KEY")
    if not key:
        return None, None
    pin = pincode if re.fullmatch(r"\d{6}", pincode or "") else os.getenv("QC_PINCODE", "")
    lat, lon = os.getenv("QC_LAT", "12.9021"), os.getenv("QC_LON", "77.6639")
    if pincode and pin == pincode:
        g = await geocode(pin)
        if g:
            lat, lon = g
    params = {"q": q, "lat": lat, "lon": lon, "platforms": platforms or os.getenv("QC_PLATFORMS", "BlinkIt,Zepto,Swiggy,BigBasket,JioMart,Minutes")}
    if pin:
        params["pincode"] = pin
    url = os.getenv("QC_API_URL") or "https://api.quickcommerceapi.com/v1/groupsearch"
    err = None
    async with httpx.AsyncClient(timeout=30) as c:
        for attempt in range(3):
            try:
                r = await c.get(url, params=params, headers={"X-API-Key": key})
            except httpx.HTTPError as e:
                print(f"[QuickCommerce] request failed: {e!r}")
                err = "QuickCommerce timed out or is unreachable."
                await asyncio.sleep(0.7 * (attempt + 1))
                continue
            if r.status_code == 200:
                try:
                    items = parse_results(r.json())
                except Exception:
                    return None, "QuickCommerce sent an unreadable response."
                return (items or None), (None if items else "No products found for this search.")
            print(f"[QuickCommerce] HTTP {r.status_code}: {r.text[:300]}")
            if r.status_code in (401, 403):
                return None, "QuickCommerce rejected the API key."
            if r.status_code == 402:
                return None, "QuickCommerce credits are used up."
            if r.status_code == 429:
                err = "QuickCommerce rate limit reached."
                try:
                    wait = float(r.headers.get("retry-after", "1"))
                except ValueError:
                    wait = 1
                await asyncio.sleep(min(wait, 4))
                continue
            if r.status_code >= 500:
                err = "QuickCommerce is having problems."
                await asyncio.sleep(0.7 * (attempt + 1))
                continue
            return None, f"QuickCommerce returned an error ({r.status_code})."
    return None, err

# ---------- AI ----------
async def ai_json(system: str, user: str) -> Optional[dict]:
    grok = os.getenv("AI_PROVIDER", "openai").lower() == "grok"
    key = os.getenv("XAI_API_KEY") if grok else os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    url = "https://api.x.ai/v1/chat/completions" if grok else "https://api.openai.com/v1/chat/completions"
    model = os.getenv("AI_MODEL") or ("grok-3-mini" if grok else "gpt-4o-mini")
    body = {"model": model, "temperature": 0.3, "messages": [
        {"role": "system", "content": system + " Respond with a single valid JSON object only."},
        {"role": "user", "content": user}]}
    if not grok:
        body["response_format"] = {"type": "json_object"}
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, headers={"Authorization": f"Bearer {key}"}, json=body)
            r.raise_for_status()
            txt = r.json()["choices"][0]["message"]["content"]
        txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
        return json.loads(txt)
    except Exception:
        return None

def slim(p):
    return {k: p.get(k) for k in ("id", "name", "brand", "price", "mrp", "discount", "rating", "reviews_count", "platform", "features")}

W = {"quality": .35, "value": .25, "trust": .15, "deal": .15, "speed": .10}
PRIO = {"price": "value", "rating": "quality", "reviews": "trust", "deals": "deal"}

def parts_of(p, maxp):
    n = p["reviews_count"]
    adj = (p["rating"] * n + 3.8 * 50) / (n + 50)  # Bayesian average: few reviews pull toward 3.8
    return {"quality": adj / 5, "value": 1 - p["price"] / maxp if maxp else 0,
            "trust": min(math.log10(n + 1) / 5.5, 1), "deal": min(p["discount"], 60) / 60,
            "speed": (1 - min(p.get("eta", 0), 60) / 60) if p.get("eta") else .5}

def rank(products, budget=0, prios=(), profile=None):
    """Cartwise Score 0-100: quality 35%, value 25%, trust 15%, deals 15%, speed 10%, tuned by priorities."""
    if not products:
        return []
    maxp = max(p["price"] for p in products) or 1
    w = dict(W)
    for k in prios:
        if k in PRIO:
            w[PRIO[k]] += .12
    tot = sum(w.values())
    out = []
    for p in products:
        parts = parts_of(p, maxp)
        p["parts"] = {k: round(v * 100) for k, v in parts.items()}
        s = sum(w[k] * parts[k] for k in w) / tot * 100
        if budget and p["price"] > budget:
            s -= 25
        if profile:
            if p.get("platform") in profile.get("platforms", []): s += 4
            ap = profile.get("avg_price") or 0
            if ap and abs(p["price"] - ap) / ap <= .3: s += 4
            if any(t in p["name"].lower() for t in profile.get("terms", []) if len(t) > 2): s += 4
        out.append((p, max(0, min(100, round(s)))))
    return sorted(out, key=lambda x: -x[1])

def score_all(items):
    for p, s in rank(items):
        p["score"] = s

# ---------- models ----------
class CompareIn(BaseModel):
    products: list[dict[str, Any]]

class RecommendIn(BaseModel):
    query: str = ""
    budget: float = 0
    priorities: list[str] = []
    products: list[dict[str, Any]]

class ReviewIn(BaseModel):
    product: dict[str, Any]

class SaveIn(BaseModel):
    client_id: str
    product: dict[str, Any]

# ---------- Neon PostgreSQL (asyncpg) with in-memory fallback ----------
import asyncpg
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

MEM: dict[str, dict[str, dict]] = {}
POOL = None
POOL_LOCK = asyncio.Lock()
SCHEMA = """
create table if not exists searches (
  id bigint generated always as identity primary key,
  client_id text, query text not null, created_at timestamptz default now());
create table if not exists saved_products (
  id bigint generated always as identity primary key,
  client_id text not null, product_id text not null, product jsonb not null,
  created_at timestamptz default now(), unique (client_id, product_id));
create table if not exists users (
  id bigint generated always as identity primary key,
  name text not null, email text unique not null, password_hash text not null,
  created_at timestamptz default now());
create table if not exists price_history (
  id bigint generated always as identity primary key,
  product_id text not null, name text, platform text, price double precision not null,
  seen_at timestamptz default now());
create index if not exists price_history_idx on price_history (product_id, seen_at);
create table if not exists alerts (
  id bigint generated always as identity primary key,
  user_key text not null, product_id text not null, product jsonb not null,
  target_price double precision not null, active boolean default true,
  triggered_price double precision, triggered_at timestamptz,
  created_at timestamptz default now(), unique (user_key, product_id));
alter table alerts add column if not exists email text;
alter table alerts add column if not exists pincode text;
alter table alerts add column if not exists notified boolean default false;
"""

def db_ready():
    return bool(os.getenv("DATABASE_URL"))

def clean_dsn(u: str) -> str:
    p = urlsplit(u.strip().strip('"').strip("'"))
    q = [(k, v) for k, v in parse_qsl(p.query) if k != "channel_binding"]
    return urlunsplit(p._replace(query=urlencode(q)))

async def pool():
    global POOL
    async with POOL_LOCK:
        if POOL is None:
            p = await asyncpg.create_pool(clean_dsn(os.getenv("DATABASE_URL")), min_size=1, max_size=5,
                                          statement_cache_size=0, command_timeout=20)
            async with p.acquire() as c:
                await c.execute(SCHEMA)  # tables are created automatically
            POOL = p
    return POOL


# ---------- Auth (sign up / sign in) ----------
SECRET = os.getenv("JWT_SECRET") or secrets.token_hex(32)  # set JWT_SECRET so logins survive restarts
USERS: dict[str, dict] = {}

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def _sig(body: str) -> str:
    return _b64(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest())

def make_token(user: dict) -> str:
    body = _b64(json.dumps({"sub": str(user["id"]), "name": user["name"], "email": user["email"],
                            "exp": int(time.time()) + 7 * 86400}).encode())
    return f"{body}.{_sig(body)}"

def read_token(t: str) -> Optional[dict]:
    try:
        body, sig = t.split(".")
        if not hmac.compare_digest(sig, _sig(body)):
            return None
        p = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return p if p["exp"] > time.time() else None
    except Exception:
        return None

def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    return salt.hex() + "$" + hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32).hex()

def check_pw(pw: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$")
        return hmac.compare_digest(hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32).hex(), h)
    except Exception:
        return False

def owner(request: Request, client_id: str) -> str:
    p = read_token(request.headers.get("authorization", "").replace("Bearer ", "").strip())
    return f"user:{p['sub']}" if p else client_id

async def find_user(email: str) -> Optional[dict]:
    if db_ready():
        try:
            row = await (await pool()).fetchrow("select id, name, email, password_hash from users where email = $1", email)
            if row:
                return dict(row)
        except Exception:
            pass
    return USERS.get(email)

async def add_user(name: str, email: str, ph: str) -> dict:
    if db_ready():
        try:
            row = await (await pool()).fetchrow(
                "insert into users (name, email, password_hash) values ($1, $2, $3) returning id, name, email", name, email, ph)
            return dict(row)
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, "An account with this email already exists.")
        except Exception:
            pass
    if email in USERS:
        raise HTTPException(409, "An account with this email already exists.")
    USERS[email] = {"id": f"m{len(USERS) + 1}", "name": name, "email": email, "password_hash": ph}
    return USERS[email]

class SignupIn(BaseModel):
    name: str = ""
    email: str
    password: str

class LoginIn(BaseModel):
    email: str
    password: str

@app.post("/api/auth/signup")
async def signup(request: Request, b: SignupIn):
    limit(request, "auth", 10)
    email = b.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "Enter a valid email address.")
    if len(b.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters.")
    if await find_user(email):
        raise HTTPException(409, "An account with this email already exists.")
    name = b.name.strip()[:60] or email.split("@")[0]
    u = await add_user(name, email, hash_pw(b.password))
    return {"token": make_token(u), "user": {"name": u["name"], "email": u["email"]}}

@app.post("/api/auth/login")
async def login(request: Request, b: LoginIn):
    limit(request, "auth", 10)
    u = await find_user(b.email.strip().lower())
    if not u or not check_pw(b.password, u["password_hash"]):
        raise HTTPException(401, "Wrong email or password.")
    return {"token": make_token(u), "user": {"name": u["name"], "email": u["email"]}}

@app.get("/api/auth/me")
async def me(request: Request):
    p = read_token(request.headers.get("authorization", "").replace("Bearer ", "").strip())
    if not p:
        raise HTTPException(401, "Not signed in.")
    return {"user": {"name": p["name"], "email": p["email"]}}

# ---------- routes ----------
@app.get("/api/health")
def health():
    ai = os.getenv("XAI_API_KEY") if os.getenv("AI_PROVIDER", "").lower() == "grok" else os.getenv("OPENAI_API_KEY")
    return {"ok": True, "ai": bool(ai), "products": bool(os.getenv("QC_API_KEY")), "db": db_ready(), "email": email_ready()}

# ---------- cache, rate limits, db helper ----------
CACHE: dict = {}
AI_CACHE: dict = {}
HITS: dict = {}
TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))

def limit(request: Request, bucket: str, n: int, per: int = 60):
    ip = request.client.host if request.client else "?"
    now = time.time()
    hits = [t for t in HITS.get((bucket, ip), []) if now - t < per]
    if len(hits) >= n:
        HITS[(bucket, ip)] = hits
        wait = int(per - (now - hits[0])) + 1
        raise HTTPException(429, f"Too many requests. Please wait {wait}s and try again.", headers={"Retry-After": str(wait)})
    hits.append(now)
    HITS[(bucket, ip)] = hits

async def dbq(sql, *a, mode="all"):
    if not db_ready():
        return None
    try:
        p = await pool()
        if mode == "exec": return await p.execute(sql, *a)
        if mode == "one": return await p.fetchrow(sql, *a)
        return await p.fetch(sql, *a)
    except Exception as e:
        print("[db]", repr(e))
        return None

def need_user(request: Request) -> str:
    w = owner(request, "")
    if not w.startswith("user:"):
        raise HTTPException(401, "Sign in to use this feature.")
    return w

async def log_search(who, q):
    await dbq("insert into searches (client_id, query) values ($1, $2)", who, q, mode="exec")

async def track(items):
    """Record price history and trigger price-drop alerts for freshly fetched products."""
    ids = [p["id"] for p in items]
    rows = await dbq("select distinct on (product_id) product_id, price, seen_at from price_history "
                     "where product_id = any($1::text[]) order by product_id, seen_at desc", ids)
    if rows is None:
        return
    last = {r["product_id"]: (r["price"], r["seen_at"]) for r in rows}
    now = datetime.now(timezone.utc)
    new = [(p["id"], p["name"], p["platform"], float(p["price"])) for p in items if p["price"] > 0 and (
        p["id"] not in last or last[p["id"]][0] != p["price"] or (now - last[p["id"]][1]).total_seconds() > 21600)]
    if new:
        try:
            await (await pool()).executemany("insert into price_history (product_id, name, platform, price) values ($1,$2,$3,$4)", new)
        except Exception as e:
            print("[db]", repr(e))
    await check_alerts(items)

def email_ready():
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASS"))

def _send(msg):
    with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "587")), timeout=20) as srv:
        srv.starttls()
        srv.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
        srv.send_message(msg)

async def send_email(to: str, subject: str, body: str) -> bool:
    if not email_ready() or not to:
        return False
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER")
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    try:
        await asyncio.to_thread(_send, msg)
        return True
    except Exception as e:
        print("[email]", repr(e))
        return False

async def check_alerts(items):
    by = {p["id"]: p for p in items}
    rows = await dbq("select id, product_id, target_price, email, notified from alerts where active and product_id = any($1::text[])", list(by))
    for r in rows or []:
        p = by[r["product_id"]]
        if p["price"] <= r["target_price"]:
            await dbq("update alerts set active = false, triggered_price = $2, triggered_at = now() where id = $1", r["id"], float(p["price"]), mode="exec")
            if r["email"] and not r["notified"]:
                body = (f"Good news! {p['name']} on {p['platform']} is now Rs {p['price']:.0f} "
                        f"(your target was Rs {r['target_price']:.0f}).\n\n{p.get('link') or ''}\n\n- Cartwise")
                if await send_email(r["email"], f"Price drop: {p['name'][:60]}", body):
                    await dbq("update alerts set notified = true where id = $1", r["id"], mode="exec")

PLAT_RAW = {"Instamart": "Swiggy", "Flipkart Minutes": "Minutes", "Blinkit": "BlinkIt"}

async def recheck(rows):
    """Re-fetch each alerted product from its own store only (1 API credit each) and run history + alerts."""
    done, err = set(), None
    for r in rows:
        pr = json.loads(r["product"])
        key = (pr.get("name"), r["pincode"] or "", pr.get("platform"))
        if key in done:
            continue
        done.add(key)
        items, err = await fetch_quickcommerce(pr.get("name", ""), r["pincode"] or "", PLAT_RAW.get(pr.get("platform"), pr.get("platform") or ""))
        if items:
            await track(items)
    return len(done), err

async def alert_loop():
    mins = int(os.getenv("ALERT_CHECK_MINUTES", "720") or 0)
    if mins <= 0:
        return
    await asyncio.sleep(60)
    while True:
        try:
            if os.getenv("QC_API_KEY") and db_ready():
                rows = await dbq("select product, pincode from alerts where active order by random() limit $1", int(os.getenv("ALERT_MAX_PER_CYCLE", "10")))
                if rows:
                    await recheck(rows)
        except Exception as e:
            print("[alerts]", repr(e))
        await asyncio.sleep(mins * 60)

@app.on_event("startup")
async def _start_alert_loop():
    app.state.alert_task = asyncio.create_task(alert_loop())

async def get_profile(w):
    if not w.startswith("user:"):
        return None
    sv = await dbq("select product from saved_products where client_id = $1", w) or []
    prods = [json.loads(r["product"]) for r in sv]
    terms = await dbq("select lower(query) t, count(*) c from searches where client_id = $1 group by 1 order by 2 desc limit 5", w) or []
    if not prods and not terms:
        return None
    plats = Counter(p.get("platform") for p in prods if p.get("platform")).most_common(2)
    prices = [p["price"] for p in prods if p.get("price")]
    return {"platforms": [x for x, _ in plats], "avg_price": sum(prices) / len(prices) if prices else 0, "terms": [r["t"] for r in terms]}

@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    print("[error]", repr(exc))
    return JSONResponse({"detail": "Something went wrong on the server. Please try again."}, status_code=500)

@app.get("/api/search")
async def search(request: Request, q: str = Query("", max_length=120), client_id: str = "", pincode: str = ""):
    limit(request, "search", 20)
    q, pin = q.strip(), pincode.strip()
    has_key = bool(os.getenv("QC_API_KEY"))
    if not q and has_key:  # page just opened: spend no credits, show no fake data
        return {"source": "idle", "products": []}
    who = owner(request, client_id)
    key = f"{q.lower()}|{pin}|{os.getenv('QC_PLATFORMS', '')}"
    hit = CACHE.get(key)
    cached = warning = None
    if q and hit and time.time() - hit[0] < TTL:
        items, source, cached = hit[1], "live", int(time.time() - hit[0])
    else:
        items, err = (await fetch_quickcommerce(q, pin)) if q else (None, None)
        warning = err
        if items:
            source = "live"
            CACHE[key] = (time.time(), items)
            if len(CACHE) > 200:
                CACHE.pop(next(iter(CACHE)))
            asyncio.create_task(track(items))
        elif hit:  # API failed: serve the last good result
            items, source, cached = hit[1], "live", int(time.time() - hit[0])
            warning = f"{err or 'Live search failed.'} Showing your last results."
        else:
            items, source = demo_products(q), ("fallback" if has_key else "demo")
    if q:
        asyncio.create_task(log_search(who, q))
    score_all(items)
    return {"source": source, "products": items, "cached_seconds": cached, "warning": warning}

@app.post("/api/compare")
async def compare(request: Request, body: CompareIn):
    limit(request, "ai", 15)
    ps = body.products[:4]
    ranked = rank(ps)
    cheapest = min(ps, key=lambda p: p["price"])["id"]
    best_r = max(ps, key=lambda p: p["rating"])["id"]
    best_d = max(ps, key=lambda p: p["discount"])["id"]
    most = max(ps, key=lambda p: p["reviews_count"])["id"]
    fallback_items = []
    for p in ps:
        pros, cons = [], []
        if p["id"] == cheapest: pros.append("Lowest price of the group")
        if p["id"] == best_r: pros.append("Highest customer rating")
        if p["id"] == best_d and p["discount"] > 0: pros.append(f"Biggest discount ({p['discount']}% off)")
        if p["id"] == most: pros.append("Most reviewed, so the rating is more reliable")
        if p["rating"] < 4: cons.append("Rated below 4 stars")
        if p["id"] != cheapest and p["price"] > min(x["price"] for x in ps) * 1.4: cons.append("Noticeably pricier than alternatives")
        fallback_items.append({"id": p["id"], "pros": pros or ["Solid all-rounder"], "cons": cons or ["No major drawbacks found"]})
    winner = ranked[0][0]
    fb = {"ai": False, "winner_id": winner["id"], "items": fallback_items,
          "verdict": f"{winner['name']} offers the best balance of rating ({winner['rating']}/5), price and popularity in this comparison. Add an AI key for a deeper written analysis."}
    res = await ai_json(
        "You are a sharp, honest shopping analyst. Compare the products using only the data given. "
        'Return JSON: {"verdict": "3-4 sentence recommendation", "winner_id": "id", "items": [{"id": "id", "pros": ["max 3"], "cons": ["max 3"]}]}.',
        json.dumps([slim(p) for p in ps]))
    if res and res.get("winner_id") and isinstance(res.get("items"), list):
        res["ai"] = True
        return res
    return fb

@app.post("/api/recommend")
async def recommend(request: Request, body: RecommendIn):
    limit(request, "ai", 15)
    profile = await get_profile(owner(request, ""))
    ranked = rank(body.products, body.budget, body.priorities, profile)
    picks = [{"id": p["id"], "score": s, "reason": ""} for p, s in ranked]
    top = ranked[0][0] if ranked else None
    summary = (f"Best match: {top['name']} at ₹{int(top['price']):,}, rated {top['rating']}/5." if top else "No products to rank.")
    res = await ai_json(
        "You are a personal shopping advisor. Rank ALL given products for this shopper. "
        'Return JSON: {"summary": "2-3 sentences", "picks": [{"id": "id", "score": 0-100, "reason": "one short sentence"}]} ordered best first.',
        json.dumps({"need": body.query, "budget": body.budget or "none", "priorities": body.priorities,
                    "products": [slim(p) for p in body.products], "shopper_profile": profile}))
    if res and isinstance(res.get("picks"), list) and res["picks"]:
        ids = {p["id"] for p in body.products}
        res["picks"] = [x for x in res["picks"] if x.get("id") in ids]
        if res["picks"]:
            res["ai"] = True
            res["personalized"] = bool(profile)
            return res
    for pk in picks[:3]:
        pk["reason"] = "Strong blend of rating, price and popularity for your priorities."
    return {"ai": False, "personalized": bool(profile), "summary": summary, "picks": picks}

POS = {"good", "great", "best", "superb", "excellent", "love", "comfortable", "premium", "clear", "bright", "value", "bass", "secure", "lasts"}
NEG = {"bad", "poor", "slow", "buggy", "dim", "stopped", "drops", "average", "plasticky", "bulky", "off", "worse", "broken"}

@app.post("/api/reviews")
async def reviews(request: Request, body: ReviewIn):
    limit(request, "ai", 15)
    p = body.product
    ck = f"{p.get('id')}|{p.get('rating')}|{p.get('reviews_count')}"
    if ck in AI_CACHE and time.time() - AI_CACHE[ck][0] < 86400:
        return AI_CACHE[ck][1]
    revs = p.get("reviews") or []
    res = await ai_json(
        "You analyse product reviews. If few reviews are given, infer cautiously from rating and features and say so. "
        'Return JSON: {"positive": int, "neutral": int, "negative": int (sum 100), "summary": "2 sentences", '
        '"themes": [{"label": "short", "sentiment": "positive|negative"}]} with 4-6 themes.',
        json.dumps({"product": slim(p), "reviews": revs}))
    if res and all(k in res for k in ("positive", "neutral", "negative")):
        res["ai"] = True
        AI_CACHE[ck] = (time.time(), res)
        return res
    pos = neg = 0
    for r in revs:
        w = set(re.findall(r"[a-z]+", str(r).lower()))
        pos += len(w & POS); neg += len(w & NEG)
    r5 = float(p.get("rating") or 3.5)
    base = max(10, min(85, round((r5 - 2) / 3 * 80)))
    if pos + neg:
        base = round((base + pos / (pos + neg) * 100) / 2)
    neu = 15
    positive = max(5, min(90, base - 5)); negative = max(5, 100 - positive - neu)
    positive = 100 - neu - negative
    themes = [{"label": f, "sentiment": "positive"} for f in (p.get("features") or [])[:3]]
    if r5 < 4: themes.append({"label": "Mixed durability reports", "sentiment": "negative"})
    return {"ai": False, "positive": positive, "neutral": neu, "negative": negative, "themes": themes,
            "summary": f"Estimated from a {r5}/5 rating and {len(revs)} sample reviews. Add an AI key for a full review analysis."}

@app.get("/api/saved")
async def saved(request: Request, client_id: str):
    client_id = owner(request, client_id)
    if db_ready():
        try:
            rows = await (await pool()).fetch("select product from saved_products where client_id = $1 order by created_at desc", client_id)
            return {"items": [json.loads(r["product"]) for r in rows]}
        except Exception:
            pass
    return {"items": list(MEM.get(client_id, {}).values())}

@app.post("/api/saved")
async def save(request: Request, body: SaveIn):
    body.client_id = owner(request, body.client_id)
    pid = str(body.product.get("id"))
    MEM.setdefault(body.client_id, {})[pid] = body.product
    if db_ready():
        try:
            await (await pool()).execute(
                "insert into saved_products (client_id, product_id, product) values ($1, $2, $3::jsonb) "
                "on conflict (client_id, product_id) do update set product = excluded.product",
                body.client_id, pid, json.dumps(body.product))
        except Exception:
            pass
    return {"ok": True}

@app.delete("/api/saved")
async def unsave(request: Request, client_id: str, product_id: str):
    client_id = owner(request, client_id)
    MEM.get(client_id, {}).pop(product_id, None)
    if db_ready():
        try:
            await (await pool()).execute("delete from saved_products where client_id = $1 and product_id = $2", client_id, product_id)
        except Exception:
            pass
    return {"ok": True}

class AlertIn(BaseModel):
    product: dict[str, Any]
    target_price: float
    pincode: str = ""

class CheckIn(BaseModel):
    pincode: str = ""

@app.post("/api/alerts")
async def alert_set(request: Request, b: AlertIn):
    w = need_user(request)
    if b.target_price <= 0:
        raise HTTPException(422, "Enter a price above 0.")
    if not db_ready():
        raise HTTPException(503, "Alerts need the database. Add DATABASE_URL to .env.")
    tp = read_token(request.headers.get("authorization", "").replace("Bearer ", "").strip()) or {}
    pin = b.pincode.strip() if re.fullmatch(r"\d{6}", b.pincode.strip()) else ""
    await dbq("insert into alerts (user_key, product_id, product, target_price, email, pincode) values ($1, $2, $3::jsonb, $4, $5, $6) "
              "on conflict (user_key, product_id) do update set target_price = excluded.target_price, product = excluded.product, "
              "email = excluded.email, pincode = excluded.pincode, notified = false, active = true, triggered_price = null, triggered_at = null",
              w, str(b.product.get("id")), json.dumps(b.product), float(b.target_price), tp.get("email"), pin, mode="exec")
    await check_alerts([b.product])
    return {"ok": True}

@app.get("/api/alerts")
async def alert_list(request: Request):
    w = need_user(request)
    rows = await dbq("select product, target_price, active, triggered_price, triggered_at from alerts where user_key = $1 order by created_at desc", w) or []
    return {"items": [{"product": json.loads(r["product"]), "target": r["target_price"], "active": r["active"],
                       "triggered_price": r["triggered_price"], "triggered_at": r["triggered_at"].isoformat() if r["triggered_at"] else None} for r in rows]}

@app.delete("/api/alerts")
async def alert_del(request: Request, product_id: str):
    await dbq("delete from alerts where user_key = $1 and product_id = $2", need_user(request), product_id, mode="exec")
    return {"ok": True}

@app.post("/api/alerts/check")
async def alert_check(request: Request, b: CheckIn):
    w = need_user(request)
    limit(request, "check", 3)
    rows = await dbq("select product, pincode from alerts where user_key = $1 and active limit 5", w) or []
    n, err = await recheck([{"product": r["product"], "pincode": r["pincode"] or b.pincode.strip()} for r in rows])
    return {"checked": n, "error": err}

@app.get("/api/history")
async def history(product_id: str):
    rows = await dbq("select price, seen_at from price_history where product_id = $1 order by seen_at", product_id) or []
    return {"points": [{"t": r["seen_at"].isoformat(), "price": r["price"]} for r in rows], "db": db_ready()}

@app.get("/api/dashboard")
async def dashboard(request: Request):
    w = need_user(request)
    n = lambda r, k="c": int(r[k]) if r else 0
    s = await dbq("select count(*) c from searches where client_id = $1", w, mode="one")
    wl = await dbq("select count(*) c from saved_products where client_id = $1", w, mode="one")
    al = await dbq("select count(*) filter (where active) a, count(*) filter (where not active and triggered_at is not null) t from alerts where user_key = $1", w, mode="one")
    days = await dbq("select to_char(date_trunc('day', created_at), 'DD Mon') d, count(*) c from searches where client_id = $1 "
                     "and created_at > now() - interval '14 days' group by date_trunc('day', created_at) order by date_trunc('day', created_at)", w) or []
    top = await dbq("select lower(query) t, count(*) c from searches where client_id = $1 group by 1 order by 2 desc limit 6", w) or []
    plat = await dbq("select coalesce(product->>'platform', 'Other') p, count(*) c from saved_products where client_id = $1 group by 1 order by 2 desc", w) or []
    return {"stats": {"searches": n(s), "wishlist": n(wl), "alerts_active": n(al, "a"), "alerts_triggered": n(al, "t")},
            "searches_by_day": [{"d": r["d"], "c": r["c"]} for r in days], "top_terms": [{"t": r["t"], "c": r["c"]} for r in top],
            "wishlist_by_platform": [{"p": r["p"], "c": r["c"]} for r in plat], "profile": await get_profile(w)}

@app.get("/")
def index():
    return FileResponse(FRONT / "index.html")

app.mount("/static", StaticFiles(directory=FRONT), name="static")
