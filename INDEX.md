# 🤖 NanoClaw Repository Index

**Repository:** krantikaridev/nanoclaw  
**Language:** Python (98.7%)  
**License:** MIT  
**Status:** Active Trading Bot

---

## 📋 Project Overview

**NanoClaw** is an automated cryptocurrency trading bot for Polygon network that:
- Executes real swaps on QuickSwap (USDT ↔ WETH)
- Uses BrainAgent AI for trading decisions
- Runs on a 15-minute cron schedule
- Implements 10-minute cooldown between trades
- Currently OPERATIONAL with real fund execution

---

## 🏗️ Core Files

### **Trading Engine**
| File | Purpose | Status |
|------|---------|--------|
| `clean_swap.py` | Main bot entry point, orchestrates approve + swap | ✅ Active |
| `brain_agent.py` | AI decision maker (STRAT1/STRAT2 selection) | ✅ Working |
| `swap_utils.py` | Utility functions for swap operations | ✅ Ready |

### **Configuration & State**
| File | Purpose | Usage |
|------|---------|-------|
| `.env` | API keys, wallet, RPC endpoints, token addresses | **REQUIRED** |
| `bot_state.json` | Persistent state (last_run timestamp) | Auto-created |
| `config_real.py` | Real trading parameters | Reference |

### **Monitoring & Logs**
| File | Purpose |
|------|---------|
| `real_cron.log` | Cron execution logs (append mode) |
| `combined_dashboard.md` | Status dashboard |
| `daily_status.md` | Daily performance summary |

### **Test & Development Files**
| File | Purpose | Status |
|------|---------|--------|
| `minimal_real_swap.py` | Minimal swap example | Reference |
| `backtester.py` | Backtesting framework | Testing |
| `real_parallel_runner.py` | Multi-threaded testing | Dev |

### **Strategy Files** (Not Currently Active)
- `strategy_momentum.py` - Momentum-based trading
- `strategy_surebet.py` - Arbitrage detection
- `strategy_polymarket.py` - Polymarket integration
- `strategy_hybrid.py` - Hybrid approach

---

## 🔧 Environment Setup

### **Required .env Variables**
```bash
# Blockchain
POLYGON_PRIVATE_KEY=0x...          # Wallet private key
RPC=https://polygon.drpc.org       # Default included

# Token Addresses (Polygon Mainnet)
USDT=0xc2132D05D31c914a87C6611C10748AEb04B58e8F
WETH=0x7ceB23fD6bC0adD59E62ac25578270cF1d1c495e
ROUTER=0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A07a97
