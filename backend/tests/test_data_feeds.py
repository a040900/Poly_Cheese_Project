"""
🧀 CheeseDog - 數據獲取驗證腳本
獨立測試所有外部數據源是否能正常獲取數據。
可在部署到 VPS 後單獨執行以確認連通性。

使用方式:
    cd cheeseproject/backend
    python -m tests.test_data_feeds
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# 將專案根目錄加入 Python 路徑
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp

# ═══════════════════════════════════════════════════════════════
# 測試配置
# ═══════════════════════════════════════════════════════════════
BINANCE_REST = "https://api.binance.com/api/v3"
BINANCE_WS = "wss://stream.binance.com/stream"
PM_GAMMA = "https://gamma-api.polymarket.com/events"
PM_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
POLYGON_RPC = "https://polygon-rpc.com"
CHAINLINK_AGGREGATOR = "0xc907E116054Ad103354f2D350FD2514433D57F6f"

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"


def header(title):
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


async def test_binance_rest():
    """測試 Binance REST API"""
    print("\n── Binance REST API ──────────────────────────────────")
    results = {}

    async with aiohttp.ClientSession() as session:
        # 1. 伺服器連通性
        try:
            async with session.get(
                f"{BINANCE_REST}/ping",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    results["ping"] = True
                    print(f"  {PASS} /ping 連通正常 (HTTP {resp.status})")
                else:
                    results["ping"] = False
                    print(f"  {FAIL} /ping 失敗 (HTTP {resp.status})")
        except Exception as e:
            results["ping"] = False
            print(f"  {FAIL} /ping 連線失敗: {e}")

        # 2. 伺服器時間
        try:
            async with session.get(
                f"{BINANCE_REST}/time",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                server_time = data.get("serverTime")
                local_time = int(time.time() * 1000)
                diff_ms = abs(local_time - server_time)
                results["time"] = diff_ms < 5000
                print(f"  {PASS if results['time'] else WARN} 伺服器時間差: {diff_ms}ms")
        except Exception as e:
            results["time"] = False
            print(f"  {FAIL} /time 失敗: {e}")

        # 3. BTCUSDT 最新價格
        try:
            async with session.get(
                f"{BINANCE_REST}/ticker/price",
                params={"symbol": "BTCUSDT"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                price = float(data.get("price", 0))
                results["price"] = price > 0
                print(f"  {PASS if results['price'] else FAIL} BTCUSDT 價格: ${price:,.2f}")
        except Exception as e:
            results["price"] = False
            print(f"  {FAIL} 價格獲取失敗: {e}")

        # 4. K 線歷史數據
        try:
            async with session.get(
                f"{BINANCE_REST}/klines",
                params={"symbol": "BTCUSDT", "interval": "1m", "limit": 5},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                results["klines"] = isinstance(data, list) and len(data) > 0
                if results["klines"]:
                    last = data[-1]
                    print(f"  {PASS} K 線數據: 收到 {len(data)} 根")
                    print(f"      最新 1m 收盤: ${float(last[4]):,.2f} | 成交量: {float(last[5]):,.2f}")
                else:
                    print(f"  {FAIL} K 線數據為空")
        except Exception as e:
            results["klines"] = False
            print(f"  {FAIL} K 線獲取失敗: {e}")

        # 5. 訂單簿深度
        try:
            async with session.get(
                f"{BINANCE_REST}/depth",
                params={"symbol": "BTCUSDT", "limit": 5},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                bids = data.get("bids", [])
                asks = data.get("asks", [])
                results["depth"] = len(bids) > 0 and len(asks) > 0
                if results["depth"]:
                    best_bid = float(bids[0][0])
                    best_ask = float(asks[0][0])
                    spread = best_ask - best_bid
                    print(f"  {PASS} 訂單簿: 買一 ${best_bid:,.2f} | 賣一 ${best_ask:,.2f} | 價差 ${spread:.2f}")
                else:
                    print(f"  {FAIL} 訂單簿數據為空")
        except Exception as e:
            results["depth"] = False
            print(f"  {FAIL} 訂單簿獲取失敗: {e}")

    return results


async def test_binance_ws():
    """測試 Binance WebSocket"""
    print("\n── Binance WebSocket ─────────────────────────────────")
    results = {}

    url = f"{BINANCE_WS}?streams=btcusdt@trade"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                url,
                heartbeat=20,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as ws:
                print(f"  {PASS} WebSocket 連線成功")
                results["connect"] = True

                # 等待接收第一條交易消息
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=10)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        pay = data.get("data", {})
                        price = float(pay.get("p", 0))
                        qty = float(pay.get("q", 0))
                        is_buy = "買入" if not pay.get("m") else "賣出"
                        results["trade"] = price > 0
                        print(f"  {PASS} 收到實時交易: ${price:,.2f} × {qty:.6f} ({is_buy})")
                    else:
                        results["trade"] = False
                        print(f"  {FAIL} 收到非文字訊息: {msg.type}")
                except asyncio.TimeoutError:
                    results["trade"] = False
                    print(f"  {FAIL} 10秒內未收到交易數據")

    except Exception as e:
        results["connect"] = False
        results["trade"] = False
        print(f"  {FAIL} WebSocket 連線失敗: {e}")

    return results


async def test_polymarket_rest():
    """測試 Polymarket Gamma API"""
    print("\n── Polymarket Gamma REST API ──────────────────────────")
    results = {}

    async with aiohttp.ClientSession() as session:
        # 1. 搜尋 BTC 15m 市場
        try:
            now_ts = int(time.time())
            ts_15m = (now_ts // 900) * 900
            slug_direct = f"btc-updown-15m-{ts_15m}"

            # 嘗試直接 slug
            async with session.get(
                PM_GAMMA,
                params={"slug": slug_direct, "limit": 1},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()

            if data and len(data) > 0:
                event = data[0]
                results["market_found"] = True
                print(f"  {PASS} 直接 slug 查詢成功: {slug_direct}")
                print(f"      市場標題: {event.get('title', 'N/A')}")
            else:
                # 嘗試系列搜尋
                print(f"  {WARN} 直接 slug '{slug_direct}' 未找到市場，嘗試系列搜尋...")
                async with session.get(
                    PM_GAMMA,
                    params={"slug": "btc-up-or-down-15m", "limit": 5, "closed": "false"},
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    data = await resp.json()

                if data and len(data) > 0:
                    event = data[0]
                    results["market_found"] = True
                    print(f"  {PASS} 系列搜尋成功")
                    print(f"      市場標題: {event.get('title', 'N/A')}")
                    print(f"      Slug: {event.get('ticker', 'N/A')}")
                else:
                    # 嘗試更寬泛的搜尋
                    print(f"  {WARN} 系列搜尋也未找到，嘗試寬泛搜尋...")
                    async with session.get(
                        PM_GAMMA,
                        params={"tag": "crypto", "limit": 10, "closed": "false"},
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as resp:
                        data = await resp.json()

                    btc_events = [e for e in data if "btc" in e.get("ticker", "").lower() or "bitcoin" in e.get("title", "").lower()]
                    if btc_events:
                        event = btc_events[0]
                        results["market_found"] = True
                        print(f"  {PASS} 寬泛搜尋找到 BTC 相關市場: {event.get('title', 'N/A')}")
                    else:
                        results["market_found"] = False
                        print(f"  {WARN} 未找到活躍的 BTC 15m 市場（可能目前無活躍市場）")
                        print(f"      API 返回: {len(data)} 個事件")
                        if data:
                            print(f"      第一個事件: {data[0].get('title', 'N/A')}")

            # 2. 提取 Token IDs 和價格
            if results.get("market_found") and event:
                markets = event.get("markets", [])
                if markets:
                    market = markets[0]
                    try:
                        token_ids = json.loads(market.get("clobTokenIds", "[]"))
                        results["token_ids"] = len(token_ids) >= 2
                        if results["token_ids"]:
                            print(f"  {PASS} Token IDs: [{token_ids[0][:20]}..., {token_ids[1][:20]}...]")
                        else:
                            print(f"  {FAIL} Token IDs 不足: {token_ids}")
                    except Exception as e:
                        results["token_ids"] = False
                        print(f"  {FAIL} Token IDs 解析失敗: {e}")

                    try:
                        outcomes = json.loads(market.get("outcomePrices", "[]"))
                        if len(outcomes) >= 2:
                            up_price = float(outcomes[0])
                            down_price = float(outcomes[1])
                            results["prices"] = up_price > 0 or down_price > 0
                            print(f"  {PASS} 合約價格: UP=${up_price:.4f} | DOWN=${down_price:.4f}")
                        else:
                            results["prices"] = False
                            print(f"  {WARN} 價格數據不完整")
                    except Exception as e:
                        results["prices"] = False
                        print(f"  {FAIL} 價格解析失敗: {e}")

                    # 流動性
                    liquidity = market.get("liquidity", "N/A")
                    volume = market.get("volume", "N/A")
                    print(f"      流動性: ${liquidity} | 成交量: ${volume}")

        except Exception as e:
            results["market_found"] = False
            print(f"  {FAIL} Polymarket API 請求失敗: {e}")

    return results


async def test_polymarket_ws():
    """測試 Polymarket WebSocket"""
    print("\n── Polymarket WebSocket ──────────────────────────────")
    results = {}

    # 需要先有 Token IDs
    # 嘗試獲取
    token_ids = []
    try:
        async with aiohttp.ClientSession() as session:
            now_ts = int(time.time())
            ts_15m = (now_ts // 900) * 900
            slug = f"btc-updown-15m-{ts_15m}"

            for search_params in [
                {"slug": slug, "limit": 1},
                {"slug": "btc-up-or-down-15m", "limit": 5, "closed": "false"},
            ]:
                async with session.get(
                    PM_GAMMA, params=search_params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()
                    if data and data[0].get("markets"):
                        ids = json.loads(data[0]["markets"][0].get("clobTokenIds", "[]"))
                        if len(ids) >= 2:
                            token_ids = ids
                            break
    except:
        pass

    if not token_ids:
        print(f"  {WARN} 無法獲取 Token IDs，跳過 WebSocket 測試")
        results["connect"] = None
        return results

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                PM_WS,
                heartbeat=20,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as ws:
                await ws.send_json({
                    "assets_ids": token_ids,
                    "type": "market"
                })
                results["connect"] = True
                print(f"  {PASS} WebSocket 連線成功，已訂閱 Token")

                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=15)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        results["data"] = True
                        if isinstance(data, list):
                            print(f"  {PASS} 收到初始市場數據 ({len(data)} 條)")
                        elif isinstance(data, dict):
                            print(f"  {PASS} 收到市場事件: {data.get('event_type', 'unknown')}")
                        else:
                            print(f"  {PASS} 收到數據: {str(data)[:100]}")
                    else:
                        results["data"] = False
                        print(f"  {WARN} 收到非文字訊息: {msg.type}")
                except asyncio.TimeoutError:
                    results["data"] = False
                    print(f"  {WARN} 15秒內未收到數據（可能市場不活躍）")

    except Exception as e:
        results["connect"] = False
        print(f"  {FAIL} WebSocket 連線失敗: {e}")

    return results


async def test_chainlink():
    """測試 Chainlink (Polygon RPC)"""
    print("\n── Chainlink / Polygon RPC ───────────────────────────")
    results = {}

    async with aiohttp.ClientSession() as session:
        # 1. RPC 連通性
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_blockNumber",
                "params": [],
                "id": 1,
            }
            async with session.post(
                POLYGON_RPC,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if "result" in data:
                    block = int(data["result"], 16)
                    results["rpc"] = True
                    print(f"  {PASS} Polygon RPC 連通: 最新區塊 #{block:,}")
                else:
                    results["rpc"] = False
                    print(f"  {FAIL} RPC 返回錯誤: {data.get('error', 'unknown')}")
        except Exception as e:
            results["rpc"] = False
            print(f"  {FAIL} Polygon RPC 連線失敗: {e}")

        # 2. Chainlink decimals()
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [
                    {"to": CHAINLINK_AGGREGATOR, "data": "0x313ce567"},
                    "latest",
                ],
                "id": 2,
            }
            async with session.post(
                POLYGON_RPC,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if "result" in data and data["result"] != "0x":
                    decimals = int(data["result"], 16)
                    results["decimals"] = True
                    print(f"  {PASS} Chainlink 精度: {decimals}")
                else:
                    results["decimals"] = False
                    print(f"  {FAIL} decimals() 返回異常: {data}")
        except Exception as e:
            results["decimals"] = False
            print(f"  {FAIL} decimals() 呼叫失敗: {e}")

        # 3. Chainlink latestRoundData()
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [
                    {"to": CHAINLINK_AGGREGATOR, "data": "0xfeaf968c"},
                    "latest",
                ],
                "id": 3,
            }
            async with session.post(
                POLYGON_RPC,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if "result" in data and len(data["result"]) > 66:
                    hex_data = data["result"][2:]
                    answer_hex = hex_data[64:128]
                    answer = int(answer_hex, 16)
                    if answer > 2**255:
                        answer -= 2**256
                    decimals_val = results.get("_decimals_val", 8)
                    price = answer / (10 ** 8)
                    results["price"] = price > 1000  # BTC 應該大於 $1000
                    print(f"  {PASS} Chainlink BTC/USD: ${price:,.2f}")

                    # 提取更新時間
                    updated_hex = hex_data[192:256]
                    updated_at = int(updated_hex, 16)
                    age = int(time.time()) - updated_at
                    freshness = "新鮮" if age < 3600 else f"陳舊 ({age}秒前)"
                    print(f"      數據新鮮度: {freshness} (更新於 {age} 秒前)")
                else:
                    results["price"] = False
                    print(f"  {FAIL} latestRoundData() 返回異常")
        except Exception as e:
            results["price"] = False
            print(f"  {FAIL} latestRoundData() 呼叫失敗: {e}")

    return results


async def test_general_network():
    """測試一般網路連通性"""
    print("\n── 一般網路連通性 ───────────────────────────────────")
    results = {}

    async with aiohttp.ClientSession() as session:
        for name, url in [
            ("Google DNS", "https://dns.google/resolve?name=api.binance.com"),
            ("Binance API", "https://api.binance.com/api/v3/ping"),
            ("Polymarket API", "https://gamma-api.polymarket.com/events?limit=1"),
        ]:
            try:
                start = time.time()
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    latency = (time.time() - start) * 1000
                    ok = resp.status < 400
                    results[name] = ok
                    print(f"  {PASS if ok else FAIL} {name}: HTTP {resp.status} ({latency:.0f}ms)")
            except Exception as e:
                results[name] = False
                print(f"  {FAIL} {name}: {e}")

    return results


async def main():
    header("🧀 CheeseDog 數據獲取驗證工具")
    print(f"  測試時間: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Python: {sys.version.split()[0]}")

    all_results = {}

    # 1. 一般網路
    all_results["network"] = await test_general_network()

    # 2. Binance REST
    all_results["binance_rest"] = await test_binance_rest()

    # 3. Binance WebSocket
    all_results["binance_ws"] = await test_binance_ws()

    # 4. Polymarket REST
    all_results["polymarket_rest"] = await test_polymarket_rest()

    # 5. Polymarket WebSocket
    all_results["polymarket_ws"] = await test_polymarket_ws()

    # 6. Chainlink
    all_results["chainlink"] = await test_chainlink()

    # ── 總結報告 ─────────────────────────────────────────────
    header("📋 測試總結")

    total_tests = 0
    passed = 0
    failed = 0
    skipped = 0

    for category, results in all_results.items():
        for test_name, result in results.items():
            if test_name.startswith("_"):
                continue
            total_tests += 1
            if result is True:
                passed += 1
            elif result is False:
                failed += 1
            else:
                skipped += 1

    print(f"\n  總測試數:  {total_tests}")
    print(f"  {PASS} 通過:    {passed}")
    print(f"  {FAIL} 失敗:    {failed}")
    print(f"  {WARN} 跳過:    {skipped}")
    print()

    if failed == 0:
        print(f"  🎉 所有數據源連接正常！系統可以安全啟動。")
    elif failed <= 2:
        print(f"  {WARN} 部分數據源有問題，請檢查上方詳細輸出。")
        print(f"     系統可以啟動，但部分功能可能受影響。")
    else:
        print(f"  {FAIL} 多個數據源連接失敗，請檢查網路設定和 API 狀態。")

    print(f"\n{'═' * 60}\n")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
