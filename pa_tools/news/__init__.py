"""
News Aggregator Tool — AI-powered news digests

Week 1 MVP:
- Fetch from Feedly API (or mock news feeds)
- Summarize with Claude/Gemini
- Filter by topics Miles cares about (AI, crypto, tech)
- Export daily digest to email/Slack
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import httpx

logger = logging.getLogger(__name__)

# Configuration
FEEDLY_TOKEN = os.getenv("FEEDLY_TOKEN", "")
READWISE_TOKEN = os.getenv("READWISE_TOKEN", "")

# For summarization
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


class NewsAggregator:
    """
    Aggregate and summarize news for Miles.
    Focuses on: AI, crypto, tech, business
    """

    def __init__(self):
        self.has_feedly = bool(FEEDLY_TOKEN)
        self.has_readwise = bool(READWISE_TOKEN)
        self.has_gemini = bool(GEMINI_API_KEY)

        # Topics Miles cares about
        self.topics = {
            "ai": ["artificial intelligence", "claude", "openai", "deepseek", "agents"],
            "crypto": ["bitcoin", "ethereum", "crypto", "blockchain"],
            "tech": ["startup", "vc", "tech news", "silicon valley"],
            "business": ["revenue", "pricing", "market", "economics"],
        }

    async def fetch_feeds(self, hours: int = 24) -> Dict[str, Any]:
        """
        Fetch latest news from configured feeds.
        Falls back to mock data if APIs not available.

        Returns:
            {
                "articles": [...],
                "by_topic": {...},
                "summary": "...",
            }
        """
        if self.has_feedly:
            try:
                return await self._fetch_feedly(hours=hours)
            except Exception as e:
                logger.warning(f"Feedly fetch failed: {e}")

        logger.warning("No news API configured. Using mock data.")
        return await self._mock_feeds()

    async def _fetch_feedly(self, hours: int = 24) -> Dict[str, Any]:
        """Fetch from Feedly API"""
        headers = {
            "Authorization": f"Bearer {FEEDLY_TOKEN}",
        }

        # Get streams (feed subscriptions)
        streams_url = "https://cloud.feedly.com/v3/streams"
        params = {
            "ranked": "newest",
            "count": 50,
            "hours": hours,
        }

        articles_by_topic = {}
        all_articles = []

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    streams_url,
                    headers=headers,
                    params=params,
                    timeout=15
                )
                response.raise_for_status()
                data = response.json()

            items = data.get("items", [])

            for item in items:
                article = {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "source": item.get("origin", {}).get("title", "Unknown"),
                    "url": item.get("canonical", [{}])[0].get("href", ""),
                    "published": item.get("published", ""),
                    "summary": item.get("summary", {}).get("content", ""),
                }
                all_articles.append(article)

                # Categorize by topic
                for topic, keywords in self.topics.items():
                    title_lower = article["title"].lower()
                    if any(kw in title_lower for kw in keywords):
                        if topic not in articles_by_topic:
                            articles_by_topic[topic] = []
                        articles_by_topic[topic].append(article)
                        break

        except Exception as e:
            logger.error(f"Feedly API error: {e}")
            articles_by_topic = {t: [] for t in self.topics}

        return {
            "articles": all_articles,
            "by_topic": articles_by_topic,
            "summary": await self._summarize_articles(all_articles),
        }

    async def _mock_feeds(self) -> Dict[str, Any]:
        """Return mock news feed"""
        mock_articles = [
            {
                "title": "Claude 3.5 Released with New Capabilities",
                "source": "AI News Daily",
                "url": "https://ainews.example.com/claude-3.5",
                "summary": "Anthropic releases Claude 3.5 with improved reasoning",
                "published": datetime.now().isoformat(),
            },
            {
                "title": "Bitcoin Breaks $100k Milestone",
                "source": "Crypto Today",
                "url": "https://crypto.example.com/btc-ath",
                "summary": "Bitcoin reaches new all-time high",
                "published": (datetime.now() - timedelta(hours=2)).isoformat(),
            },
            {
                "title": "AI Startup Funding Boom Continues",
                "source": "TechCrunch",
                "url": "https://techcrunch.example.com/ai-funding",
                "summary": "AI startups raise record amounts in 2026",
                "published": (datetime.now() - timedelta(hours=4)).isoformat(),
            },
            {
                "title": "DeepSeek V3 Shows Competitive Performance",
                "source": "AI Research",
                "url": "https://airesearch.example.com/deepseek",
                "summary": "Chinese AI model matches leading competitors",
                "published": (datetime.now() - timedelta(hours=6)).isoformat(),
            },
        ]

        # Categorize
        articles_by_topic = {}
        for article in mock_articles:
            for topic, keywords in self.topics.items():
                title_lower = article["title"].lower()
                if any(kw in title_lower for kw in keywords):
                    if topic not in articles_by_topic:
                        articles_by_topic[topic] = []
                    articles_by_topic[topic].append(article)
                    break

        return {
            "articles": mock_articles,
            "by_topic": articles_by_topic,
            "summary": "4 articles across AI, Crypto, Tech topics",
        }

    async def _summarize_articles(self, articles: List[Dict]) -> str:
        """
        Summarize articles using Claude or Gemini.
        For now, return a simple count.
        """
        if not articles:
            return "No new articles"

        # Simple summary for now
        # TODO: Use Claude API to generate smarter summary
        topic_count = {}
        for article in articles:
            for topic in self.topics:
                topic_count[topic] = topic_count.get(topic, 0) + 1

        return f"Found {len(articles)} articles: " + ", ".join(
            f"{t}: {c}" for t, c in topic_count.items() if c > 0
        )

    async def generate_daily_digest(self) -> Dict[str, Any]:
        """
        Generate a formatted daily digest email.
        """
        data = await self.fetch_feeds(hours=24)

        digest = {
            "date": datetime.now().date().isoformat(),
            "title": "📰 Daily News Digest",
            "topics": {},
        }

        for topic, articles in data["by_topic"].items():
            if not articles:
                continue

            digest["topics"][topic.upper()] = {
                "count": len(articles),
                "articles": articles[:3],  # Top 3 per topic
            }

        return digest


async def run_news_digest() -> Dict[str, Any]:
    """
    Main entry point for news digest cron.
    Called daily at 7am MST.
    """
    aggregator = NewsAggregator()
    digest = await aggregator.generate_daily_digest()

    return {
        "status": "complete",
        "digest": digest,
    }


if __name__ == "__main__":
    import asyncio
    result = asyncio.run(run_news_digest())
    print(json.dumps(result, indent=2, default=str))
