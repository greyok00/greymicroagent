"""Portable web search (Windows source fallback).

Two keyless lanes: Bing RSS and DuckDuckGo HTML. No SearXNG instance and no
compiled module is required. Results carry title, url and snippet only; page
text is fetched separately by the browser service.
"""
from __future__ import annotations

import html as _html
import json
import re
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _get(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _strip(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _bing(query: str, limit: int) -> list:
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote_plus(query)
    body = _get(url)
    out = []
    for item in re.findall(r"<item>(.*?)</item>", body, re.S):
        title = re.search(r"<title>(.*?)</title>", item, re.S)
        link = re.search(r"<link>(.*?)</link>", item, re.S)
        desc = re.search(r"<description>(.*?)</description>", item, re.S)
        if link:
            out.append({"title": _strip(title.group(1)) if title else "",
                        "url": _html.unescape(link.group(1).strip()),
                        "snippet": _strip(desc.group(1))[:300] if desc else ""})
        if len(out) >= limit:
            break
    return out


def _ddg(query: str, limit: int) -> list:
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(
        "https://html.duckduckgo.com/html/", data=data,
        headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        body = resp.read().decode("utf-8", "replace")
    links = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S)
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', body, re.S)
    out = []
    for index, (href, title) in enumerate(links[:limit]):
        target = _html.unescape(href)
        if target.startswith("//duckduckgo.com/l/?") or target.startswith("/l/?"):
            query_part = urllib.parse.urlparse(target).query
            target = urllib.parse.parse_qs(query_part).get("uddg", [target])[0]
        out.append({"title": _strip(title),
                    "url": target,
                    "snippet": _strip(snippets[index])[:300] if index < len(snippets) else ""})
    return out


def research_search(query: str = "", max_results: int = 10, **kw) -> dict:
    q = str(query or kw.get("q") or "").strip()
    if not q:
        return {"ok": False, "output": "", "error": "missing argument: query"}
    limit = max(1, min(int(max_results or 10), 30))
    errors = []
    for name, lane in (("bing-rss", _bing), ("ddg-html", _ddg)):
        try:
            results = [r for r in lane(q, limit) if r.get("url", "").startswith("http")]
        except Exception as exc:
            errors.append("%s: %s" % (name, str(exc)[:160]))
            continue
        if results:
            payload = {"ok": True, "query": q, "engine": name,
                       "results": results, "count": len(results)}
            return {"ok": True, "output": json.dumps(payload, ensure_ascii=False),
                    "error": "", "query": q, "results": results,
                    "engine": name, "trust": "high"}
    return {"ok": False, "output": "",
            "error": "no search lane answered (%s)" % "; ".join(errors)[:400]}
