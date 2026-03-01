"""Adjusted strategy analysis: inverse flips + portfolio instrument filter."""
import sqlite3
import statistics
from collections import defaultdict

DB = r"D:\futures\edge\zenbot-edge\data\trades.db"
VALID_INSTRUMENTS = {"ES","MES","NQ","MNQ","GC","MGC","RTY","M2K","YM","MYM","CL","MCL"}

def is_inverse(strat):
    s = strat.lower()
    return "inv" in s or s in ("ema-runner", "ema-runner-ah")

def is_independent(strat):
    s = strat.upper()
    if s.startswith("APEX"):
        return False
    if s.startswith("PA") or s.startswith("TDFYA") or s == "SIM101":
        return False
    return True

def apply_inverse(t):
    if is_inverse(t["strategy"]):
        t["profit"] = -(t["profit"] or 0)
        orig_mae, orig_mfe = (t["mae"] or 0), (t["mfe"] or 0)
        t["mae"] = orig_mfe
        t["mfe"] = orig_mae
    return t

def load_trades(cur, where_clause="1=1"):
    cur.execute(f"""
        SELECT strategy, subStrategy, instrument, direction, qty,
               entryPrice, exitPrice, entryTime, exitTime,
               entryName, exitName, profit, commission, mae, mfe, etd,
               holdingMinutes, entryHour, entryHalfHour, entryDate
        FROM trades
        WHERE {where_clause}
        ORDER BY strategy, entryTime
    """)
    rows = [dict(r) for r in cur.fetchall()]
    filtered = [t for t in rows if is_independent(t["strategy"]) and t["instrument"] in VALID_INSTRUMENTS]
    return [apply_inverse(t) for t in filtered]

def print_strategy_block(strat_name, trades):
    profits = [t["profit"] or 0 for t in trades]
    total_pnl = sum(profits)
    winners = [p for p in profits if p > 0]
    losers = [p for p in profits if p < 0]
    scratches = [p for p in profits if p == 0]
    win_rate = len(winners) / len(trades) * 100 if trades else 0
    avg_win = statistics.mean(winners) if winners else 0
    avg_loss = statistics.mean(losers) if losers else 0
    gw, gl = sum(winners), sum(losers)
    pf = abs(gw / gl) if gl else float("inf")
    avg_mae = statistics.mean([t["mae"] or 0 for t in trades])
    avg_mfe = statistics.mean([t["mfe"] or 0 for t in trades])
    avg_hold = statistics.mean([t["holdingMinutes"] or 0 for t in trades])

    longs = [t for t in trades if t["direction"] == "Long"]
    shorts = [t for t in trades if t["direction"] == "Short"]
    long_pnl = sum(t["profit"] or 0 for t in longs)
    short_pnl = sum(t["profit"] or 0 for t in shorts)

    insts = defaultdict(list)
    for t in trades:
        insts[t["instrument"]].append(t)

    inv_tag = " [INVERSED]" if is_inverse(strat_name) else ""
    print(f"\n{'-' * 120}")
    print(f"  {strat_name}{inv_tag}")
    print(f"{'-' * 120}")
    print(f"  Trades: {len(trades):>4}  |  Win Rate: {win_rate:5.1f}%  ({len(winners)}W / {len(losers)}L / {len(scratches)}S)")
    print(f"  Net P/L: ${total_pnl:>10,.2f}  |  Avg Win: ${avg_win:>8,.2f}  |  Avg Loss: ${avg_loss:>8,.2f}  |  PF: {pf:.2f}")
    print(f"  Avg MAE: ${avg_mae:>8,.2f}  |  Avg MFE: ${avg_mfe:>8,.2f}  |  Avg Hold: {avg_hold:.0f} min")
    print(f"  Long: {len(longs)} trades ${long_pnl:>+10,.2f}  |  Short: {len(shorts)} trades ${short_pnl:>+10,.2f}")

    inst_parts = []
    for inst, it in sorted(insts.items(), key=lambda x: sum(t["profit"] or 0 for t in x[1]), reverse=True):
        ip = sum(t["profit"] or 0 for t in it)
        iwr = sum(1 for t in it if (t["profit"] or 0) > 0) / len(it) * 100
        inst_parts.append(f"{inst}({len(it)}t ${ip:>+,.0f} {iwr:.0f}%WR)")
    print(f"  Instruments: " + "  ".join(inst_parts))

    return total_pnl, len(trades), len(winners)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ==================== TODAY ====================
    today = load_trades(cur, "entryDate = '2026-02-26'")

    strats = defaultdict(list)
    for r in today:
        strats[r["strategy"]].append(r)

    print("=" * 120)
    print(f"{'TODAY (2026-02-26) -- Inverse flipped, portfolio instruments only':^120}")
    print("=" * 120)

    sorted_strats = sorted(strats.items(), key=lambda x: sum(t["profit"] or 0 for t in x[1]), reverse=True)

    gt, gtr, gw = 0, 0, 0
    for sn, tr in sorted_strats:
        pnl, cnt, wins = print_strategy_block(sn, tr)
        gt += pnl; gtr += cnt; gw += wins

    print(f"\n{'=' * 120}")
    print(f"  PORTFOLIO TOTAL: {gtr} trades | ${gt:>+12,.2f} | Overall WR: {gw/gtr*100:.1f}%")
    print(f"{'=' * 120}")

    # Time of day
    print(f"\n\n{'=' * 120}")
    print(f"{'TIME-OF-DAY (adjusted)':^120}")
    print(f"{'=' * 120}")
    hh_map = defaultdict(list)
    for r in today:
        hh_map[r["entryHalfHour"] or "unknown"].append(r["profit"] or 0)
    for hh in sorted(hh_map.keys()):
        profs = hh_map[hh]
        total = sum(profs)
        wr = sum(1 for p in profs if p > 0) / len(profs) * 100
        print(f"  {hh:>5s}  |  {len(profs):>3} trades  |  ${total:>+10,.2f}  |  WR: {wr:5.1f}%  |  Avg: ${statistics.mean(profs):>+8,.2f}")

    # ==================== MULTI-MONTH ====================
    multi = load_trades(cur, "entryDate >= '2025-12-01'")

    strats_m = defaultdict(list)
    for r in multi:
        strats_m[r["strategy"]].append(r)

    sorted_multi = sorted(strats_m.items(), key=lambda x: sum(t["profit"] or 0 for t in x[1]), reverse=True)

    print(f"\n\n{'=' * 120}")
    print(f"{'MULTI-MONTH (since 2025-12-01) -- Inverse flipped, portfolio instruments only':^120}")
    print(f"{'=' * 120}")

    print(f"\n{'Strategy':<25s} {'Trades':>7s} {'Days':>5s} {'Total P/L':>12s} {'WR':>6s} {'PF':>6s} {'AvgWin':>10s} {'AvgLoss':>10s} {'Inv?':>5s}")
    print("-" * 105)

    mg, mt = 0, 0
    for sn, tr in sorted_multi:
        profits = [t["profit"] or 0 for t in tr]
        total_pnl = sum(profits)
        mg += total_pnl
        mt += len(tr)
        days = len(set(t["entryDate"] for t in tr))
        winners = [p for p in profits if p > 0]
        losers = [p for p in profits if p < 0]
        wr = len(winners) / len(tr) * 100
        aw = statistics.mean(winners) if winners else 0
        al = statistics.mean(losers) if losers else 0
        gww, gll = sum(winners), sum(losers)
        pf = abs(gww / gll) if gll else float("inf")
        inv = "YES" if is_inverse(sn) else ""
        print(f"{sn:<25s} {len(tr):>7,d} {days:>5d} ${total_pnl:>+11,.2f} {wr:>5.1f}% {pf:>5.2f} ${aw:>9,.2f} ${al:>9,.2f} {inv:>5s}")

    print(f"\n{'=' * 120}")
    print(f"  MULTI-MONTH PORTFOLIO TOTAL: {mt} trades | ${mg:>+12,.2f}")
    print(f"{'=' * 120}")

    # ==================== DAILY CURVE LAST 10 DAYS ====================
    daily = defaultdict(lambda: defaultdict(float))
    daily_total = defaultdict(float)
    for t in multi:
        daily[t["entryDate"]][t["strategy"]] += (t["profit"] or 0)
        daily_total[t["entryDate"]] += (t["profit"] or 0)

    all_dates = sorted(daily.keys())[-10:]

    print(f"\n\n{'=' * 120}")
    print(f"{'DAILY P/L -- LAST 10 TRADING DAYS':^120}")
    print(f"{'=' * 120}")

    # Top strategies by absolute contribution
    top_strats = [s for s, _ in sorted_multi[:8]]

    print(f"\n{'Date':<12s}", end="")
    for s in top_strats:
        label = s[:12]
        print(f" {label:>12s}", end="")
    print(f" {'TOTAL':>12s}")
    print("-" * (12 + 13 * len(top_strats) + 13))

    for d in all_dates:
        print(f"{d:<12s}", end="")
        for s in top_strats:
            val = daily[d].get(s, 0)
            if val == 0:
                print(f" {'--':>12s}", end="")
            else:
                print(f" ${val:>+10,.0f} ", end="")
        print(f" ${daily_total[d]:>+10,.0f}")

    # ==================== CUMULATIVE P/L ====================
    print(f"\n\n{'=' * 120}")
    print(f"{'CUMULATIVE P/L BY STRATEGY (since 2025-12-01)':^120}")
    print(f"{'=' * 120}")

    for sn, tr in sorted_multi[:12]:
        by_date = defaultdict(float)
        for t in tr:
            by_date[t["entryDate"]] += (t["profit"] or 0)
        dates_sorted = sorted(by_date.keys())
        cum = 0
        inv = " [INV]" if is_inverse(sn) else ""
        print(f"\n  {sn}{inv}:")
        chunks = []
        for d in dates_sorted:
            cum += by_date[d]
            chunks.append(f"{d[5:]}: ${cum:>+,.0f}")
        # Print in rows of 6
        for i in range(0, len(chunks), 6):
            print(f"    " + "  |  ".join(chunks[i:i+6]))

    conn.close()


if __name__ == "__main__":
    main()
