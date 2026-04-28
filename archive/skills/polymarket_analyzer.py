#!/usr/bin/env python3
"""
Polymarket Volume Analyzer Skill
Fetches top active markets, computes volume/edge scores.
"""

import urllib.request
import json
import sys
from typing import List, Dict

BASE_URL = "https://gamma.api.polymarket.com"

def fetch_active_markets(limit: int = 20) -> List[Dict]:
    """
    Fetch top active markets from Polymarket Gamma API.
    """
    url = f"{BASE_URL}/markets?active=true&limit={limit}&sort=volume"
    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())
            return data.get('markets', [])
    except Exception as e:
        print(f"Error fetching markets: {e}", file=sys.stderr)
        return []

def analyze_market(market: Dict) -> Dict:
    """
    Calculate volume, prices, edge score.
    """
    yes_price = market.get('yes_price', 0.5)
    no_price = market.get('no_price', 0.5)
    vol_24h = market.get('volume_24h', {}).get('usd', 0) or market.get('volume_24h_usd', 0)
    liquidity = market.get('liquidity', 0) or market.get('open_interest', 0)
    
    spread = abs(yes_price - no_price)
    edge_score = "Interesting" if vol_24h > 50000 and spread < 0.05 else "Neutral"
    
    return {
        'title': market.get('question', market.get('slug', 'N/A')),
        'slug': market.get('slug', 'N/A'),
        'yes_price': f"{yes_price:.2%}",
        'no_price': f"{no_price:.2%}",
        'volume_24h_usd': vol_24h,
        'liquidity': liquidity,
        'spread': f"{spread:.3f}",
        'edge': edge_score
    }

def main(top_n: int = 5):
    """
    CLI: Print top N markets by volume.
    """
    markets = fetch_active_markets(20)
    if not markets:
        print("No markets fetched.")
        return
    
    analyzed = sorted([analyze_market(m) for m in markets], key=lambda x: x['volume_24h_usd'], reverse=True)
    
    print(f"Top {top_n} Polymarket Markets (by 24h Vol USD):\\n")
    for i, m in enumerate(analyzed[:top_n], 1):
        print(f"{i}. {m['title'][:80]}...")
        print(f"   Slug: {m['slug']}")
        print(f"   Yes/No: {m['yes_price']}/{m['no_price']} (spread: {m['spread']})")
        print(f"   Vol 24h: ${m['volume_24h_usd']:,.0f} | Liq: ${m['liquidity']:,.0f}")
        print(f"   Edge: {m['edge']}\\n")

if __name__ == "__main__":
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    main(top_n)