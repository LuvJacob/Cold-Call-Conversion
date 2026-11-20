# Demo runbook (run it on your own Mac)

About 10 minutes the first time. Everything runs locally; the only network calls are to free public sources (Wikidata, Wikipedia, SEC EDGAR) and, if you add a key, IBM watsonx.ai.

## 1. One-time setup

You need Git, Homebrew and Docker. If you don't have Docker Desktop, the free command-line option is:

```bash
brew install colima docker docker-compose
mkdir -p ~/.docker/cli-plugins && ln -sf "$(brew --prefix)/opt/docker-compose/bin/docker-compose" ~/.docker/cli-plugins/docker-compose
colima start --cpu 4 --memory 6
```

Get the code and make your local settings file:

```bash
git clone https://github.com/LuvJacob/Cold-Call-Conversion.git
cd Cold-Call-Conversion
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(24))"   # paste this as MONGO_ROOT_PASSWORD in .env
```

In `.env`, also set `SEC_USER_AGENT="ColdCallConversion research your-email@example.com"` (your own contact; SEC requires one, and without it SEC filings are skipped). `.env` is git-ignored: never commit it and never paste keys into `.env.example`.

## 2. Start it

```bash
docker compose up --build -d
```

Open **http://127.0.0.1:3000** (use `127.0.0.1`; `localhost:3000` can hit another app on your machine). The sidebar should say **Team workspace · Saved to server · LIVE**.

## 3. Demo script (about 3 minutes)

1. **Add prospect**: a real public company works best, e.g. *Satya Nadella, CEO, Microsoft, microsoft.com*.
2. Research starts automatically; the status changes in a few seconds to **Ready** or **Needs review** (partial).
3. Open the briefing: summary, cited facts (each with its source), questions, and what is uncertain. The **Live research** label means real sources; **Sample data** means a built-in fictional sample.
4. Click **Pop out briefing** (Chrome or Edge): a small window that stays on top of any app, e.g. your dialer. Move it beside the call.
5. Click **Call connected**, then end the call and pick an outcome.
6. Optional: **Import CSV** to load a calling list.

## 4. Optional: AI-written summaries (watsonx)

Without a key, facts come from free sources and the wording is a template. With IBM watsonx.ai, put these in `.env` (from your watsonx project's **Manage** tab):

```
RESEARCH_PROVIDERS=live
WATSONX_API_KEY=...
WATSONX_URL=https://us-south.ml.cloud.ibm.com
WATSONX_PROJECT_ID=...
```

Then `docker compose up -d api` and check:

```bash
curl -s http://127.0.0.1:8000/healthz/research -H 'X-Seller-ID: demo-seller'
```

It should show `"mode":"live"` and `"watsonx":true` (it only shows true/false, never the key). Paid calls: keep the demo to a few prospects. Empty Tavily/PDL keys simply fall back to the free sources.

## 5. Stop it

```bash
docker compose down        # keeps your data
docker compose down -v     # also wipes the local database
colima stop                # if you use Colima
```

## Troubleshooting

- **Page says the research service is unavailable**: the API container is down; run `docker compose ps` and `docker compose logs api`.
- **A briefing has no facts**: the company may not be in Wikidata/SEC (private or very small companies). That is expected and is flagged in the briefing.
- **Pop out briefing is greyed out**: use Chrome or Edge.
- **Offline sample-only demo** (no network): set `NEXT_PUBLIC_DATA_MODE=demo` in `.env` and run `docker compose up -d web`.
