"""NQ Long performance across every strategy."""
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime

DB = r"D:\futures\edge\zenbot-edge\data\trades.db"
EXCLUDE_PREFIXES = ["APEX","TDFY","TDY","TPT","PA","LTE","FTDY","ftd","BX","CHB","BLU","sim101"]

def is_inverse(strat):
    s = strat.lower()
    return "inv" in s or s in ("ema-runner", "ema-runner-ah")

def is_excluded(strat):
    s = strat.lower()
    return any(s.startswith(p.lower()) for p in EXCLUDE_PREFIXES)

def pf(w_list, l_list):
    gw = sum(w_list)
    gl = abs(sum(l_list))
    if gl == 0:
        return float("inf") if gw > 0 else 0
    return gw / gl

def is_rth(entry_time_str):
    try:
        if "T" in entry_time_str:
            dt = datetime.fromisoformat(entry_time_str)
        elif "AM" in entry_time_str or "PM" in entry_time_str:
            dt = datetime.strptime(entry_time_str, "%m/%d/%Y %I:%M:%S %p")
        else:
            dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
        mins = dt.hour * 60 + dt.minute
        # NQ RTH: 9:30 AM - 4:00 PM ET = 570-960 min
        return 570 <= mins < 960
    except Exception:
        return None

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT strategy, instrument, direction, profit, mae, mfe, etd,
               holdingMinutes, entryHour, entryHalfHour, entryDate, entryTime
        FROM trades
        WHERE instrument IN ('NQ','MNQ') AND direction = 'Long'
        ORDER BY strategy, entryTime
    """)
    all_trades = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Filter excluded accounts
    all_trades = [t for t in all_trades if not is_excluded(t["strategy"])]

    # Apply inverse flip
    for t in all_trades:
        if is_inverse(t["strategy"]):
            t["profit"] = -(t["profit"] or 0)
            orig_mae, orig_mfe = (t["mae"] or 0), (t["mfe"] or 0)
            t["mae"] = orig_mfe
            t["mfe"] = orig_mae

    # Group by strategy
    strats = defaultdict(list)
    for t in all_trades:
        strats[t["strategy"]].append(t)

    total_nq_trades = len(all_trades)
    total_nq_pnl = sum(t["profit"] or 0 for t in all_trades)

    print("=" * 140)
    print(f"{'NQ/MNQ LONG -- EVERY STRATEGY (adjusted for inversions)':^140}")
    print(f"{'Total: ' + str(total_nq_trades) + ' trades, $' + f'{total_nq_pnl:+,.2f}':^140}")
    print("=" * 140)

    # ======= SUMMARY TABLE =======
    results = []
    for sn, trades in strats.items():
        profits = [t["profit"] or 0 for t in trades]
        total_pnl = sum(profits)
        days = len(set(t["entryDate"] for t in trades))
        winners = [p for p in profits if p > 0]
        losers = [p for p in profits if p < 0]
        wr = len(winners) / len(trades) * 100
        avg_w = statistics.mean(winners) if winners else 0
        avg_l = statistics.mean(losers) if losers else 0
        pf_val = pf(winners, losers)
        avg_trade = statistics.mean(profits)
        first = min(t["entryDate"] for t in trades)
        last = max(t["entryDate"] for t in trades)
        inv = is_inverse(sn)

        # RTH vs ETH
        rth_t = [t for t in trades if is_rth(t["entryTime"] or "") is True]
        eth_t = [t for t in trades if is_rth(t["entryTime"] or "") is False]
        rth_pnl = sum(t["profit"] or 0 for t in rth_t)
        eth_pnl = sum(t["profit"] or 0 for t in eth_t)
        rth_w = [t["profit"] or 0 for t in rth_t if (t["profit"] or 0) > 0]
        rth_l = [t["profit"] or 0 for t in rth_t if (t["profit"] or 0) < 0]
        eth_w = [t["profit"] or 0 for t in eth_t if (t["profit"] or 0) > 0]
        eth_l = [t["profit"] or 0 for t in eth_t if (t["profit"] or 0) < 0]
        rth_pf = pf(rth_w, rth_l) if rth_t else 0
        eth_pf = pf(eth_w, eth_l) if eth_t else 0

        # NQ vs MNQ split
        nq_trades = [t for t in trades if t["instrument"] == "NQ"]
        mnq_trades = [t for t in trades if t["instrument"] == "MNQ"]

        results.append({
            "name": sn, "n": len(trades), "days": days,
            "pnl": total_pnl, "wr": wr, "pf": pf_val,
            "avg_w": avg_w, "avg_l": avg_l, "avg_trade": avg_trade,
            "first": first, "last": last, "inv": inv,
            "rth_n": len(rth_t), "rth_pnl": rth_pnl, "rth_pf": rth_pf,
            "eth_n": len(eth_t), "eth_pnl": eth_pnl, "eth_pf": eth_pf,
            "nq_n": len(nq_trades), "nq_pnl": sum(t["profit"] or 0 for t in nq_trades),
            "mnq_n": len(mnq_trades), "mnq_pnl": sum(t["profit"] or 0 for t in mnq_trades),
            "trades": trades,
        })

    results.sort(key=lambda x: x["pnl"], reverse=True)

    print(f"\n  {'Strategy':<25s} {'N':>5s} {'Days':>5s} {'P/L':>12s} {'WR':>6s} {'PF':>6s} {'$/Trade':>9s} {'Inv?':>5s} {'RTH P/L':>10s} {'ETH P/L':>10s} {'Period'}")
    print(f"  {'-' * 130}")

    for r in results:
        inv_tag = "YES" if r["inv"] else ""
        period = f"{r['first'][:7]} to {r['last'][:7]}"
        print(f"  {r['name']:<25s} {r['n']:>5d} {r['days']:>5d} ${r['pnl']:>+10,.2f} {r['wr']:>5.1f}% {r['pf']:>5.2f} ${r['avg_trade']:>+7,.2f} {inv_tag:>5s} ${r['rth_pnl']:>+8,.0f} ${r['eth_pnl']:>+8,.0f}  {period}")

    # Grand totals
    grand_pnl = sum(r["pnl"] for r in results)
    grand_n = sum(r["n"] for r in results)
    grand_w = sum(1 for r in results for t in r["trades"] if (t["profit"] or 0) > 0)
    grand_wr = grand_w / grand_n * 100 if grand_n else 0
    print(f"\n  {'GRAND TOTAL':<25s} {grand_n:>5d}       ${grand_pnl:>+10,.2f} {grand_wr:>5.1f}%")

    # ======= WINNERS vs LOSERS =======
    winners_strats = [r for r in results if r["pnl"] > 0]
    losers_strats = [r for r in results if r["pnl"] < 0]

    print(f"\n\n{'=' * 140}")
    print(f"{'NQ LONG: STRATEGIES WHERE IT WORKS vs WHERE IT FAILS':^140}")
    print(f"{'=' * 140}")

    if winners_strats:
        print(f"\n  PROFITABLE NQ Long ({len(winners_strats)} strategies):")
        for r in winners_strats:
            inv_tag = " [INV]" if r["inv"] else ""
            print(f"    {r['name']}{inv_tag}: {r['n']} trades, {r['days']} days, ${r['pnl']:>+,.2f}, PF={r['pf']:.2f}, WR={r['wr']:.1f}%")

    if losers_strats:
        print(f"\n  LOSING NQ Long ({len(losers_strats)} strategies):")
        for r in sorted(losers_strats, key=lambda x: x["pnl"]):
            inv_tag = " [INV]" if r["inv"] else ""
            print(f"    {r['name']}{inv_tag}: {r['n']} trades, {r['days']} days, ${r['pnl']:>+,.2f}, PF={r['pf']:.2f}, WR={r['wr']:.1f}%")

    # ======= DETAILED BREAKDOWN FOR TOP STRATEGIES =======
    print(f"\n\n{'=' * 140}")
    print(f"{'NQ LONG: DETAILED STRATEGY BREAKDOWNS (top 15 by trade count)':^140}")
    print(f"{'=' * 140}")

    by_count = sorted(results, key=lambda x: x["n"], reverse=True)[:15]

    for r in by_count:
        trades = r["trades"]
        inv_tag = " [INVERSED]" if r["inv"] else ""
        print(f"\n  {'~' * 120}")
        print(f"  {r['name']}{inv_tag} -- {r['n']} trades, {r['days']} days ({r['first']} to {r['last']})")
        print(f"  {'~' * 120}")
        print(f"  P/L: ${r['pnl']:>+,.2f}  |  WR: {r['wr']:.1f}%  |  PF: {r['pf']:.2f}  |  AvgWin: ${r['avg_w']:>,.2f}  |  AvgLoss: ${r['avg_l']:>,.2f}  |  $/Trade: ${r['avg_trade']:>+,.2f}")

        # NQ vs MNQ
        if r["nq_n"] > 0 and r["mnq_n"] > 0:
            print(f"  NQ: {r['nq_n']} trades ${r['nq_pnl']:>+,.2f}  |  MNQ: {r['mnq_n']} trades ${r['mnq_pnl']:>+,.2f}")
        elif r["nq_n"] > 0:
            print(f"  All NQ (full-size): {r['nq_n']} trades")
        else:
            print(f"  All MNQ (micro): {r['mnq_n']} trades")

        # RTH vs ETH
        if r["rth_n"] >= 3 and r["eth_n"] >= 3:
            rth_wr = sum(1 for t in trades if is_rth(t["entryTime"] or "") is True and (t["profit"] or 0) > 0) / r["rth_n"] * 100 if r["rth_n"] else 0
            eth_wr = sum(1 for t in trades if is_rth(t["entryTime"] or "") is False and (t["profit"] or 0) > 0) / r["eth_n"] * 100 if r["eth_n"] else 0
            sess_note = ""
            if r["rth_pf"] >= 1.15 and r["eth_pf"] < 0.90:
                sess_note = ">>> RTH ONLY"
            elif r["eth_pf"] >= 1.15 and r["rth_pf"] < 0.90:
                sess_note = ">>> ETH ONLY"
            elif r["rth_pf"] >= 1.15 and r["eth_pf"] >= 1.15:
                sess_note = "Both sessions profitable"
            elif r["rth_pf"] < 0.90 and r["eth_pf"] < 0.90:
                sess_note = "Both sessions losing"
            print(f"  RTH: {r['rth_n']} trades, ${r['rth_pnl']:>+,.2f}, PF={r['rth_pf']:.2f}, WR={rth_wr:.1f}%  |  ETH: {r['eth_n']} trades, ${r['eth_pnl']:>+,.2f}, PF={r['eth_pf']:.2f}, WR={eth_wr:.1f}%  {sess_note}")
        elif r["rth_n"] >= 1:
            print(f"  RTH only: {r['rth_n']} trades, ${r['rth_pnl']:>+,.2f}, PF={r['rth_pf']:.2f}")
        elif r["eth_n"] >= 1:
            print(f"  ETH only: {r['eth_n']} trades, ${r['eth_pnl']:>+,.2f}, PF={r['eth_pf']:.2f}")

        # Time of day breakdown
        hh_map = defaultdict(list)
        for t in trades:
            hh_map[t["entryHalfHour"] or "unknown"].append(t["profit"] or 0)

        if len(hh_map) >= 2:
            print(f"\n  Time-of-Day:")
            print(f"  {'Time':>8s} {'Trades':>7s} {'P/L':>12s} {'WR':>7s} {'$/Trade':>10s}")
            for hh in sorted(hh_map.keys()):
                profs = hh_map[hh]
                total = sum(profs)
                wr = sum(1 for p in profs if p > 0) / len(profs) * 100
                avg = statistics.mean(profs)
                bar = "+" * max(0, int(total / 200)) if total > 0 else "-" * max(0, int(-total / 200))
                print(f"  {hh:>8s} {len(profs):>7d} ${total:>+10,.2f} {wr:>6.1f}% ${avg:>+8,.2f}  {bar}")

        # Monthly P/L curve
        monthly = defaultdict(float)
        monthly_n = defaultdict(int)
        for t in trades:
            m = t["entryDate"][:7]
            monthly[m] += (t["profit"] or 0)
            monthly_n[m] += 1

        if len(monthly) >= 2:
            print(f"\n  Monthly:")
            cum = 0
            for m in sorted(monthly.keys()):
                cum += monthly[m]
                bar = "+" * max(0, int(monthly[m] / 200)) if monthly[m] > 0 else "-" * max(0, int(-monthly[m] / 200))
                print(f"    {m}: {monthly_n[m]:>3d} trades ${monthly[m]:>+8,.0f}  (cum: ${cum:>+10,.0f})  {bar}")

    # ======= SHOULD YOU INVERSE NQ LONG? =======
    print(f"\n\n{'=' * 140}")
    print(f"{'INVERSION ANALYSIS: WHAT IF YOU INVERSED NQ LONG ON EACH STRATEGY?':^140}")
    print(f"{'=' * 140}")

    print(f"\n  {'Strategy':<25s} {'N':>5s} {'Original P/L':>14s} {'Orig PF':>8s} {'Inversed P/L':>14s} {'Inv PF':>8s} {'Better':>10s} {'Confidence'}")
    print(f"  {'-' * 110}")

    for r in sorted(results, key=lambda x: x["n"], reverse=True):
        if r["n"] < 5:
            continue
        orig_pnl = r["pnl"]
        inv_pnl = -r["pnl"]
        orig_pf = r["pf"]
        # Compute inverse PF
        profits = [t["profit"] or 0 for t in r["trades"]]
        inv_w = [-p for p in profits if p < 0]
        inv_l = [-p for p in profits if p > 0]
        inv_pf = pf(inv_w, inv_l)

        better = "ORIGINAL" if orig_pf >= inv_pf else "INVERSE"
        better_pf = max(orig_pf, inv_pf)

        conf = ""
        if r["n"] >= 50 and r["days"] >= 20 and better_pf >= 1.3:
            conf = "HIGH"
        elif r["n"] >= 25 and r["days"] >= 10 and better_pf >= 1.15:
            conf = "MEDIUM"
        elif r["n"] >= 10 and better_pf >= 1.1:
            conf = "LOW"
        else:
            conf = "VERY LOW"

        print(f"  {r['name']:<25s} {r['n']:>5d} ${orig_pnl:>+12,.2f} {orig_pf:>7.2f} ${inv_pnl:>+12,.2f} {inv_pf:>7.2f} {better:>10s}  {conf}")

    # ======= AGGREGATE: ALL NQ LONG BY TIME OF DAY =======
    print(f"\n\n{'=' * 140}")
    print(f"{'ALL NQ LONG TRADES: TIME-OF-DAY AGGREGATE':^140}")
    print(f"{'=' * 140}")

    hh_all = defaultdict(list)
    for t in all_trades:
        hh_all[t["entryHalfHour"] or "unknown"].append(t["profit"] or 0)

    print(f"\n  {'Time':>8s} {'Trades':>7s} {'P/L':>12s} {'WR':>7s} {'PF':>7s} {'$/Trade':>10s}")
    print(f"  {'-' * 60}")
    for hh in sorted(hh_all.keys()):
        profs = hh_all[hh]
        total = sum(profs)
        wr = sum(1 for p in profs if p > 0) / len(profs) * 100
        avg = statistics.mean(profs)
        w = [p for p in profs if p > 0]
        l = [p for p in profs if p < 0]
        pf_val = pf(w, l)
        bar = "+" * max(0, int(total / 300)) if total > 0 else "-" * max(0, int(-total / 300))
        print(f"  {hh:>8s} {len(profs):>7d} ${total:>+10,.2f} {wr:>6.1f}% {pf_val:>6.2f} ${avg:>+8,.2f}  {bar}")

    # ======= AGGREGATE: ALL NQ LONG BY MONTH =======
    print(f"\n\n{'=' * 140}")
    print(f"{'ALL NQ LONG TRADES: MONTHLY P/L':^140}")
    print(f"{'=' * 140}")

    monthly_all = defaultdict(float)
    monthly_all_n = defaultdict(int)
    for t in all_trades:
        m = t["entryDate"][:7]
        monthly_all[m] += (t["profit"] or 0)
        monthly_all_n[m] += 1

    cum = 0
    print(f"\n  {'Month':>8s} {'Trades':>7s} {'P/L':>12s} {'Cumulative':>12s}")
    print(f"  {'-' * 45}")
    for m in sorted(monthly_all.keys()):
        cum += monthly_all[m]
        bar = "+" * max(0, int(monthly_all[m] / 500)) if monthly_all[m] > 0 else "-" * max(0, int(-monthly_all[m] / 500))
        print(f"  {m:>8s} {monthly_all_n[m]:>7d} ${monthly_all[m]:>+10,.2f} ${cum:>+10,.2f}  {bar}")


if __name__ == "__main__":
    main()
