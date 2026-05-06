import requests

TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the internet for current information: news, weather, scores, prices, "
            "facts, or anything you are unsure about or that might have changed recently. "
            "Always prefer searching over saying you don't know."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_page",
        "description": (
            "Fetch and read the full content of a web page. "
            "Use this after web_search to get detailed information from a specific URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"}
            },
            "required": ["url"],
        },
    },
]


def web_search(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddg:
            results = list(ddg.text(query, max_results=5))
        if not results:
            return "No results found."
        parts = []
        for r in results:
            parts.append(f"Title: {r['title']}\nURL: {r['href']}\nSummary: {r['body']}")
        return "\n---\n".join(parts)
    except Exception as e:
        return f"Search failed: {e}"


def fetch_page(url: str) -> str:
    try:
        from bs4 import BeautifulSoup
        r = requests.get(
            url, timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Fyra/1.0)"},
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:4000] if len(text) > 4000 else text
    except Exception as e:
        return f"Could not fetch page: {e}"


def execute_tool(name: str, inputs: dict) -> str:
    if name == "web_search":
        return web_search(inputs.get("query", ""))
    if name == "fetch_page":
        return fetch_page(inputs.get("url", ""))
    return f"Unknown tool: {name}"
