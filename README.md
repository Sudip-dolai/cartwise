# Cartwise — AI Product Comparison & Recommendation

Search quick-commerce products across stores, compare prices, features and ratings, analyse reviews with AI, and get personalised recommendations. Built with FastAPI, PostgreSQL and vanilla JavaScript.

## Features

| | Feature | Details |
|---|---|---|
| 🔎 | Product search | Live results from Blinkit, Zepto, Instamart, BigBasket, JioMart and Flipkart Minutes via [QuickCommerceAPI](https://quickcommerceapi.com), by pincode |
| 🔃 | Multi-product comparison | Compare 2–4 products side by side with charts and an AI verdict |
| 🔍 | Advanced filtering | Filter by store, rating, discount, delivery time and budget, plus several sort options |
| 🤖 | Review sentiment analysis | Positive / neutral / negative split using OpenAI or Grok |
| 📝 | AI review summaries | Short written summary with key themes |
| ⭐ | Cartwise Score | Own 0–100 scoring algorithm (see below) |
| 👤 | Personalised recommendations | Adapts to a signed-in user's favourite stores, typical price and past searches |
| ❤️ | Wishlist | Saved per account |
| 📈 | Price history | Prices are recorded over time and charted |
| 🔔 | Price-drop alerts | Set a target price; get an email and an in-app notification |
| 🔐 | Authentication | Sign up / sign in with scrypt-hashed passwords and signed session tokens |
| 🗄️ | PostgreSQL | Neon (any Postgres works) |
| 📊 | Dashboard | Search activity, top searches, wishlist by store, taste profile, alerts |
| ⚡ | Caching | Repeat searches are served from memory, saving API credits |
| 🛡️ | Error handling | Retries with backoff, rate-limit handling, graceful fallbacks, per-visitor request limits |

## Tech stack

- **Frontend:** HTML, CSS, JavaScript, [Chart.js](https://www.chartjs.org)
- **Backend:** Python, FastAPI, Uvicorn, httpx
- **Database:** PostgreSQL (Neon) via asyncpg
- **AI:** OpenAI or Grok (xAI)
- **Product data:** QuickCommerceAPI

## Project structure

```
cartwise/
├── backend/
│   ├── main.py            # API, scoring, auth, alerts, caching
│   └── requirements.txt
├── frontend/
│   └── index.html         # Single-page UI (HTML + CSS + JS)
├── .env.example           # Copy to .env and fill in
├── schema.sql             # Optional: tables are also created automatically
└── README.md
```

## Getting started

**Requirements:** Python 3.10+

```bash
git clone https://github.com/Sudip-dolai/cartwise.git
cd cartwise

python -m venv .venv
# Windows:       .venv\Scripts\activate
# macOS / Linux: source .venv/bin/activate

pip install -r backend/requirements.txt

cp .env.example .env        # Windows: copy .env.example .env
# edit .env and add your keys

uvicorn backend.main:app --reload
```

Open <http://127.0.0.1:8000>. Check <http://127.0.0.1:8000/api/health> to see which services are connected.

The app runs without any keys using built-in demo products and a rule-based fallback, so you can try it before setting anything up.

## Configuration

Set these in `.env`:

| Variable | Purpose |
|---|---|
| `AI_PROVIDER` | `openai` or `grok` |
| `OPENAI_API_KEY` / `XAI_API_KEY` | Key for the chosen provider |
| `AI_MODEL` | Optional model override |
| `QC_API_KEY` | QuickCommerceAPI key |
| `QC_PLATFORMS` | Stores to search, e.g. `BlinkIt,Zepto,Swiggy,BigBasket,JioMart,Minutes` |
| `QC_PINCODE`, `QC_LAT`, `QC_LON` | Default location when a visitor doesn't enter a pincode |
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET` | Long random string for signing logins. Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `CACHE_TTL_SECONDS` | How long search results are cached (default 900) |
| `ALERT_CHECK_MINUTES` | Automatic price re-check interval, `0` to turn off (default 720) |
| `ALERT_MAX_PER_CYCLE` | Max alerts re-checked per cycle (default 10) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | Optional email sending for price-drop alerts. For Gmail, use an [app password](https://myaccount.google.com/apppasswords) |

**Never commit your `.env` file.** It is listed in `.gitignore`.

## How the Cartwise Score works

Each product gets a score from 0 to 100:

| Component | Weight | Notes |
|---|---|---|
| Quality | 35% | Bayesian-adjusted rating, so a 5.0 from 3 reviews doesn't beat a 4.6 from 50,000 |
| Value | 25% | Price relative to the other results |
| Trust | 15% | Review count, on a log scale |
| Deals | 15% | Discount versus MRP |
| Speed | 10% | Delivery time |

Choosing priorities (low price, high rating, etc.) shifts the weights. Going over budget lowers the score, and signed-in users get a small bonus for their usual stores, price range and search topics.

## API overview

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/search` | Search products (`q`, `pincode`) |
| POST | `/api/compare` | AI comparison of selected products |
| POST | `/api/recommend` | Ranked, optionally personalised recommendations |
| POST | `/api/reviews` | Sentiment and summary for a product |
| GET / POST / DELETE | `/api/saved` | Wishlist |
| GET | `/api/history` | Price history for a product |
| GET / POST / DELETE | `/api/alerts` | Price-drop alerts (sign-in required) |
| POST | `/api/alerts/check` | Re-check alerted products now |
| GET | `/api/dashboard` | User analytics |
| POST | `/api/auth/signup`, `/api/auth/login` | Authentication |
| GET | `/api/health` | Which services are configured |

Interactive docs are available at `/docs` while the server is running.

## Limitations

- QuickCommerceAPI returns star ratings and review counts but not review text, so AI sentiment and summaries are estimates based on that data.
- Price history builds up over time as products appear in searches.
- Caching and rate limiting are in memory, so they reset on restart and aren't shared between multiple server processes.
- Automatic alert checks only run while the server is running and use API credits.
- There is no password reset or email verification yet.

## License

Add a license of your choice (for example MIT) before publishing.
