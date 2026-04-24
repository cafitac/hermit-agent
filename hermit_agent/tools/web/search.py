"""WebSearchTool — DuckDuckGo + Google News RSS search."""

from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import requests

from ..base import Tool, ToolResult


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web for current information. Returns search results with titles, URLs, and snippets."
    is_read_only = True
    is_concurrent_safe = True

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    def execute(self, input: dict) -> ToolResult:
        query = input["query"]
        max_results = input.get("max_results", 5)

        # Use Google News RSS first when news keywords are detected
        news_keywords = ["news", "latest", "recent", "today", "this week",
                         "headline", "breaking", "scraping"]
        is_news = any(k in query.lower() for k in news_keywords)

        if is_news:
            google_results = self._search_google_news(query, max_results)
            if google_results:
                return ToolResult(content=google_results)

        ddg_results = self._search_ddg(query, max_results)

        if not ddg_results:
            google_results = self._search_google_news(query, max_results)
            if google_results:
                return ToolResult(content=google_results)
            return ToolResult(content=f"No results found for: {query}")

        lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(ddg_results, 1):
            title = r.get("title", "(no title)")
            url = r.get("href", "")
            snippet = r.get("body", "")
            lines.append(f"{i}. {title}")
            lines.append(f"   URL: {url}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")

        return ToolResult(content="\n".join(lines))

    def _search_ddg(self, query: str, max_results: int) -> list[dict]:
        try:
            try:
                from ddgs import DDGS as _PrimaryDDGS
                ddgs_cls: Any = _PrimaryDDGS
            except ImportError:
                from duckduckgo_search import DDGS as _FallbackDDGS
                ddgs_cls = _FallbackDDGS
            return ddgs_cls().text(query, max_results=max_results) or []
        except Exception:
            return []

    def _search_google_news(self, query: str, max_results: int) -> str:
        encoded = urllib.parse.quote(query)
        lang = "ko" if any('\uac00' <= c <= '\ud7a3' for c in query) else "en"
        url = f"https://news.google.com/rss/search?q={encoded}&hl={lang}&gl={'KR' if lang == 'ko' else 'US'}&ceid={'KR:ko' if lang == 'ko' else 'US:en'}"

        try:
            resp = requests.get(url, headers={"User-Agent": "HermitAgent/0.1"}, timeout=15)
            resp.raise_for_status()
            xml_data = resp.content.decode("utf-8")

            root = ET.fromstring(xml_data)
            items = root.findall(".//item")
            if not items:
                return ""

            lines = [f"Google News results for: {query}\n"]
            for i, item in enumerate(items[:max_results], 1):
                title = item.findtext("title", "(no title)")
                link = item.findtext("link", "")
                pub_date = item.findtext("pubDate", "")
                source = item.findtext("source", "")
                lines.append(f"{i}. {title}")
                if source:
                    lines.append(f"   Source: {source}")
                lines.append(f"   URL: {link}")
                if pub_date:
                    lines.append(f"   Date: {pub_date}")
                lines.append("")

            return "\n".join(lines)
        except Exception:
            return ""


__all__ = ["WebSearchTool"]
