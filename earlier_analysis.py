"""Analyze earlier/undiscussed strategies from the expanded database."""
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime

DB = r"D:\futures\edge\zenbot-edge\data\trades.db"
VALID = {"ES","MES","NQ","MNQ","GC","MGC","RTY","M2K","YM","MYM","CL","MCL"}
EXCLUDE_PREFIXES = ["APEX","TDFY","TDY","TPT","PA","LTE","FTDY","ftd","BX","CHB","BLU","sim101"]
ALREADY_DISCUSSED = {
    "Levels","Levels-2M","Levels-3M","Levels-5M","Levels-10M","Levels-15M",
    "Level-Inv-1M","Level-Inv-2M","Level-Inv-3M","Level-Inv-5M",
    "Snappy-1M","Snappy-2M","Snappy-3M","Snappy-5M",
    "Snappy-2M-AH","Snappy-3M-AH","Snappy-1M-Inv",
    "ZenTrend","ZenTrend-2M","ZenTrend-3M","ZenTrend-5M",
    "VWMA-Wick-1M","VWMA-Wick-2M","VWMA-Cross","VWMA-Crossover-2M",
    "EMA-1M","EMA-2M","EMA-3M","EMA-5M","EMA-2X",
    "EMA-Runner","EMA-Runner-AH","EMA-Runner-Inv",
    "ZoneBot","HA-Rev-1M",
}

def is_excluded(strat):
    s = strat.lower()
    return any(s.startswith(p.lower()) for p in EXCLUDE_PREFIXES)

def pf(w_list, l_list):
    gw = sum(w_list)
    gl = abs(sum(l_list))
    if gl == 0:
        return float("inf") if gw > 0 else 0
    return gw / gl

def is_rth(instrument, entry_time_str):
    try:
        if "T" in entry_time_str:
            dt = datetime.fromisoformat(entry_time_str)
        elif "AM" in entry_time_str or "PM" in entry_time_str:
            dt = datetime.strptime(entry_time_str, "%m/%d/%Y %I:%M:%S %p")
        else:
            dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
        mins = dt.hour * 60 + dt.minute
        if instrument in ("ES","MES","NQ","MNQ","RTY","M2K","YM","MYM"):
            return 570 <= mins < 960
        elif instrument in ("CL","MCL"):
            return 540 <= mins < 870
        elif instrument in ("GC","MGC"):
            return 500 <= mins < 810
    except Exception:
        pass
    return None

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    conds = " AND ".join([f"LOWER(strategy) NOT LIKE '{p.lower()}%'" for p in EXCLUDE_PREFIXES])
    cur.execute(f"""
        SELECT strategy, instrument, direction, profit, mae, mfe, etd,
               holdingMinutes, entryHour, entryHalfHour, entryDate, entryTime
        FROM trades
        WHERE {conds}
        ORDER BY strategy, entryTime
    """)
    all_trades = [dict(r) for r in cur.fetchall()]
    conn.close()

    strats = defaultdict(list)
    for t in all_trades:
        strats[t["strategy"]].append(t)

    # Only new strategies, with valid instruments, >= 10 trades
    new_strats = {}
    for k, v in strats.items():
        if k in ALREADY_DISCUSSED:
            continue
        valid = [t for t in v if t["instrument"] in VALID]
        if len(valid) >= 10:
            new_strats[k] = valid

    print("=" * 140)
    print(f"{'DETAILED ANALYSIS OF EARLIER/UNDISCUSSED STRATEGIES':^140}")
    print(f"{'(Portfolio instruments only)':^140}")
    print("=" * 140)

    results = []
    for sn, trades in new_strats.items():
        profits = [t["profit"] or 0 for t in trades]
        total_pnl = sum(profits)
        days = len(set(t["entryDate"] for t in trades))
        winners = [p for p in profits if p > 0]
        losers = [p for p in profits if p < 0]
        wr = len(winners) / len(trades) * 100
        avg_w = statistics.mean(winners) if winners else 0
        avg_l = statistics.mean(losers) if losers else 0
        orig_pf = pf(winners, losers)
        inv_w = [-p for p in profits if p < 0]
        inv_l = [-p for p in profits if p > 0]
        inv_pf_val = pf(inv_w, inv_l)
        first = min(t["entryDate"] for t in trades)
        last = max(t["entryDate"] for t in trades)

        results.append({
            "name": sn, "trades": trades, "n": len(trades), "days": days,
            "pnl": total_pnl, "wr": wr, "pf": orig_pf, "inv_pf": inv_pf_val,
            "avg_w": avg_w, "avg_l": avg_l, "first": first, "last": last,
        })

    results.sort(key=lambda x: max(x["pf"], x["inv_pf"]), reverse=True)

    for r in results:
        trades = r["trades"]
        better = "ORIGINAL" if r["pf"] >= r["inv_pf"] else "INVERSE"
        better_pf = max(r["pf"], r["inv_pf"])
        better_pnl = r["pnl"] if better == "ORIGINAL" else -r["pnl"]

        if better_pf >= 1.3 and r["n"] >= 30 and r["days"] >= 10:
            rating = "*** PROMISING"
        elif better_pf >= 1.15 and r["n"] >= 20 and r["days"] >= 5:
            rating = "**  WORTH EXPLORING"
        elif better_pf >= 1.05 and r["n"] >= 50:
            rating = "*   MARGINAL EDGE"
        elif better_pf < 0.90 and r["inv_pf"] < 0.90:
            rating = "    NO EDGE"
        else:
            rating = "    INCONCLUSIVE"

        print(f"\n{'~' * 140}")
        print(f"  {r['name']}  --  {r['n']} trades, {r['days']} days ({r['first']} to {r['last']})  [{rating}]")
        print(f"{'~' * 140}")
        print(f"  Original:  ${r['pnl']:>+12,.2f}  WR={r['wr']:.1f}%  PF={r['pf']:.2f}  AvgW=${r['avg_w']:>,.2f}  AvgL=${r['avg_l']:>,.2f}")
        print(f"  Inversed:  ${-r['pnl']:>+12,.2f}  WR={100-r['wr']:.1f}%  PF={r['inv_pf']:.2f}")
        print(f"  Best direction: {better} (PF={better_pf:.2f}, P/L=${better_pnl:>+,.2f})")

        # Symbol x Direction
        combos = defaultdict(list)
        for t in trades:
            combos[(t["instrument"], t["direction"])].append(t["profit"] or 0)

        print(f"\n  {'Symbol':<8s} {'Dir':<6s} {'Trades':>6s} {'P/L':>12s} {'WR':>7s} {'PF':>7s} {'InvPF':>7s} {'$/Trade':>9s}  Notes")
        print(f"  {'-' * 90}")

        for (inst, dirn), profs in sorted(combos.items(), key=lambda x: sum(x[1]), reverse=True):
            n = len(profs)
            pnl_c = sum(profs)
            w = [p for p in profs if p > 0]
            l = [p for p in profs if p < 0]
            wr_c = len(w) / n * 100
            pf_c = pf(w, l)
            ipf_c = pf([-p for p in l], [-p for p in w])
            per = pnl_c / n
            note = ""
            if pf_c >= 1.3 and n >= 15:
                note = "++ STRONG"
            elif pf_c >= 1.15 and n >= 10:
                note = "+  Good"
            elif ipf_c >= 1.3 and n >= 15:
                note = "++ STRONG INVERSE"
            elif ipf_c >= 1.15 and n >= 10:
                note = "+  Good inverse"
            elif n < 10:
                note = "low sample"
            print(f"  {inst:<8s} {dirn:<6s} {n:>6d} ${pnl_c:>+10,.2f} {wr_c:>6.1f}% {pf_c:>6.2f} {ipf_c:>6.2f} ${per:>8,.2f}  {note}")

        # RTH vs ETH
        rth_t = [t for t in trades if is_rth(t["instrument"], t["entryTime"] or "") is True]
        eth_t = [t for t in trades if is_rth(t["instrument"], t["entryTime"] or "") is False]

        if len(rth_t) >= 5 and len(eth_t) >= 5:
            rth_profs = [t["profit"] or 0 for t in rth_t]
            eth_profs = [t["profit"] or 0 for t in eth_t]
            rw = [p for p in rth_profs if p > 0]
            rl = [p for p in rth_profs if p < 0]
            ew = [p for p in eth_profs if p > 0]
            el = [p for p in eth_profs if p < 0]
            rpf = pf(rw, rl)
            epf = pf(ew, el)
            sess_note = ""
            if rpf >= 1.15 and epf < 0.90:
                sess_note = ">>> RTH ONLY"
            elif epf >= 1.15 and rpf < 0.90:
                sess_note = ">>> ETH ONLY"
            elif rpf >= 1.15 and epf >= 1.15:
                sess_note = "Both good"
            elif rpf < 0.90 and epf < 0.90:
                sess_note = "Both weak"
            print(f"\n  Session: RTH={len(rth_t)}t ${sum(rth_profs):>+,.0f} PF={rpf:.2f}  |  "
                  f"ETH={len(eth_t)}t ${sum(eth_profs):>+,.0f} PF={epf:.2f}  {sess_note}")

    # Summary table
    print(f"\n\n{'=' * 140}")
    print(f"{'SUMMARY: STRATEGIES RANKED BY BEST-DIRECTION PF':^140}")
    print(f"{'=' * 140}")
    print(f"\n  {'Strategy':<25s} {'Trades':>7s} {'Days':>5s} {'Period':<27s} {'Best Dir':<10s} {'Best PF':>8s} {'Best P/L':>12s} {'Rating'}")
    print(f"  {'-' * 110}")
    for r in results:
        better = "ORIGINAL" if r["pf"] >= r["inv_pf"] else "INVERSE"
        better_pf = max(r["pf"], r["inv_pf"])
        better_pnl = r["pnl"] if better == "ORIGINAL" else -r["pnl"]
        period = f"{r['first']} to {r['last']}"

        if better_pf >= 1.3 and r["n"] >= 30 and r["days"] >= 10:
            rating = "*** PROMISING"
        elif better_pf >= 1.15 and r["n"] >= 20 and r["days"] >= 5:
            rating = "**  WORTH EXPLORING"
        elif better_pf >= 1.05 and r["n"] >= 50:
            rating = "*   MARGINAL"
        else:
            rating = ""
        print(f"  {r['name']:<25s} {r['n']:>7d} {r['days']:>5d} {period:<27s} {better:<10s} {better_pf:>7.2f} ${better_pnl:>+11,.2f}  {rating}")


if __name__ == "__main__":
    main()
