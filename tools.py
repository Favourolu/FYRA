import requests
from datetime import datetime

AFRITERMINAL_BASE = "<https://favourolu.github.io/afriterminal>"

TOOLS = [
    {"name":"web_search","description":"Search the internet for current information: news, weather, scores, prices, facts, or anything you are unsure about or that might have changed recently. Always prefer searching over saying you don't know.","input_schema":{"type":"object","properties":{"query":{"type":"string","description":"The search query"}},"required":["query"]}},
    {"name":"fetch_page","description":"Fetch and read the full content of a web page. Use this after web_search to get detailed information from a specific URL.","input_schema":{"type":"object","properties":{"url":{"type":"string","description":"The URL to fetch"}},"required":["url"]}},
    {"name":"fetch_afriterminal_data","description":"Fetch live African market data from AfriTerminal. Use this for ANY question about NGX stocks, Nigerian or African market prices, corporate filings, FX rates, bond yields, CBN macro data, or global markets. Always fetch before answering market questions — never invent figures. Dataset options: ngx_prices, market_summary, filings, fx, bonds, macro, global, market_flows.","input_schema":{"type":"object","properties":{"dataset":{"type":"string","description":"Which dataset: ngx_prices (live NGX stock prices for ALL companies — use for any individual stock price e.g. GTCO Zenith MTN), market_summary (NGX breadth top gainers top losers), filings (NGX corporate disclosures), fx (NGN/GHS/KES/ZAR/EGP rates), bonds (sovereign bond yields), macro (CBN MPR inflation reserves), global (S&P500 FTSE Nikkei oil gold), market_flows (institutional/foreign/retail participation)"}},"required":["dataset"]}},
]

def web_search(query):
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddg:
            results = list(ddg.text(query, max_results=5))
        if not results: return "No results found."
        return "\n---\n".join(f"Title: {r['title']}\nURL: {r['href']}\nSummary: {r['body']}" for r in results)
    except Exception as e: return f"Search failed: {e}"

def fetch_page(url):
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0 (compatible; Fyra/1.0)"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script","style","nav","footer","header","aside"]): tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:4000] if len(text) > 4000 else text
    except Exception as e: return f"Could not fetch page: {e}"

def fetch_afriterminal_data(dataset):
    urls = {
        "ngx_prices": f"{AFRITERMINAL_BASE}/ngx_live_prices.csv",
        "market_summary": f"{AFRITERMINAL_BASE}/digest.json",
        "filings": f"{AFRITERMINAL_BASE}/filings.json",
        "fx": f"{AFRITERMINAL_BASE}/fx_rates.csv",
        "bonds": f"{AFRITERMINAL_BASE}/bonds_data.json",
        "macro": f"{AFRITERMINAL_BASE}/macro_data.csv",
        "global": f"{AFRITERMINAL_BASE}/global_markets.json",
        "market_flows": f"{AFRITERMINAL_BASE}/market_flows.json",
    }
    url = urls.get(dataset)
    if not url: return f"Unknown dataset '{dataset}'. Options: {list(urls.keys())}"
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent":"Fyra/1.0"})
        r.raise_for_status()
        return f"[AfriTerminal · {dataset} · {datetime.now().strftime('%Y-%m-%d %H:%M')} WAT]\n{r.text[:8000]}"
    except Exception as e: return f"Could not fetch AfriTerminal {dataset}: {e}"

def execute_tool(name, inputs):
    if name == "web_search": return web_search(inputs.get("query",""))
    if name == "fetch_page": return fetch_page(inputs.get("url",""))
    if name == "fetch_afriterminal_data": return fetch_afriterminal_data(inputs.get("dataset",""))
    return f"Unknown tool: {name}"
