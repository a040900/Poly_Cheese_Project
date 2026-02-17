"""快速檢查系統狀態"""
import urllib.request
import json

try:
    r = urllib.request.urlopen("http://localhost:8888/api/status")
    d = json.loads(r.read())

    print("=" * 50)
    print("  🧀 CheeseDog 系統狀態")
    print("=" * 50)

    m = d.get("market", {})
    btc = m.get("btc_price")
    print(f"\n  BTC 價格:      ${btc:,.2f}" if btc else "\n  BTC 價格:      連線中...")

    pm_up = m.get("pm_up_price")
    pm_dn = m.get("pm_down_price")
    print(f"  PM UP 價格:    ${pm_up}" if pm_up else "  PM UP 價格:    連線中...")
    print(f"  PM DOWN 價格:  ${pm_dn}" if pm_dn else "  PM DOWN 價格:  連線中...")

    cl = m.get("chainlink_price")
    print(f"  Chainlink:     ${cl:,.2f}" if cl else "  Chainlink:     連線中...")

    sig = d.get("signal", {})
    print(f"\n  信號方向:      {sig.get('direction', 'N/A')}")
    print(f"  偏差分數:      {sig.get('score', 'N/A')}")

    conn = d.get("connections", {})
    for name in ["binance", "polymarket", "chainlink"]:
        c = conn.get(name, {})
        ok = c.get("connected", False)
        icon = "✅" if ok else "❌"
        print(f"  {name:15s} {icon}")

    t = d.get("trading", {})
    sim = t.get("simulation", {})
    print(f"\n  交易模式:      {t.get('mode_name', 'N/A')}")
    print(f"  模擬餘額:      ${sim.get('balance', 0):,.2f}")
    print(f"  總交易數:      {sim.get('total_trades', 0)}")
    print(f"  總盈虧:        ${sim.get('total_pnl', 0):,.4f}")
    print(f"\n{'=' * 50}")

except Exception as e:
    print(f"❌ 無法連線系統: {e}")
