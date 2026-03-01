"""Deep analysis: symbol/direction/timeframe optimization per strategy."""
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime

DB = r"D:\futures\edge\zenbot-edge\data\trades.db"
VALID_INSTRUMENTS = {"ES","MES","NQ","MNQ","GC","MGC","RTY","M2K","YM","MYM","CL","MCL"}

# RTH windows (Eastern time)
# ES/NQ/RTY/YM: 9:30-16:00
# CL: 9:00-14:30
# GC: 8:20-13:30
RTH_WINDOWS = {
    "ES": (9,30, 16,0), "MES": (9,30, 16,0),
    "NQ": (9,30, 16,0), "MNQ": (9,30, 16,0),
    "RTY": (9,30, 16,0), "M2K": (9,30, 16,0),
    "YM": (9,30, 16,0), "MYM": (9,30, 16,0),
    "CL": (9,0, 14,30), "MCL": (9,0, 14,30),
    "GC": (8,20, 13,30), "MGC": (8,20, 13,30),
}

def is_rth(instrument, entry_time_str):
    """Determine if a trade entered during RTH."""
    try:
        if "T" in entry_time_str:
            dt = datetime.fromisoformat(entry_time_str)
        elif "AM" in entry_time_str or "PM" in entry_time_str:
            dt = datetime.strptime(entry_time_str, "%m/%d/%Y %I:%M:%S %p")
        else:
            dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
    except:
        return None

    w = RTH_WINDOWS.get(instrument)
    if not w:
        return None
    open_h, open_m, close_h, close_m = w
    entry_mins = dt.hour * 60 + dt.minute
    open_mins = open_h * 60 + open_m
    close_mins = close_h * 60 + close_m
    return open_mins <= entry_mins < close_mins

def is_inverse(strat):
    s = strat.lower()
    return "inv" in s or s in ("ema-runner", "ema-runner-ah", "ema-runner-inv")

def is_independent(strat):
    s = strat.upper()
    if s.startswith("APEX"):
        return False
    if s.startswith("PA") or s.startswith("TDFYA") or s == "SIM101":
        return False
    return True

def pf(winners, losers):
    gw = sum(winners)
    gl = abs(sum(losers))
    if gl == 0:
        return float("inf") if gw > 0 else 0
    return gw / gl

def analyze_group(trades):
    """Return stats dict for a group of trades."""
    if not trades:
        return None
    profits = [t["adj_profit"] for t in trades]
    total = sum(profits)
    w = [p for p in profits if p > 0]
    l = [p for p in profits if p < 0]
    wr = len(w) / len(profits) * 100
    avg_w = statistics.mean(w) if w else 0
    avg_l = statistics.mean(l) if l else 0
    return {
        "n": len(trades),
        "pnl": total,
        "wr": wr,
        "pf": pf(w, l),
        "avg_w": avg_w,
        "avg_l": avg_l,
        "wins": len(w),
        "losses": len(l),
    }

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT strategy, subStrategy, instrument, direction, qty,
               entryPrice, exitPrice, entryTime, exitTime,
               entryName, exitName, profit, commission, mae, mfe, etd,
               holdingMinutes, entryHour, entryHalfHour, entryDate
        FROM trades
        WHERE entryDate >= '2025-12-01'
        ORDER BY strategy, entryTime
    """)
    all_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Filter and apply adjustments
    trades = []
    for t in all_rows:
        if not is_independent(t["strategy"]):
            continue
        if t["instrument"] not in VALID_INSTRUMENTS:
            continue
        inv = is_inverse(t["strategy"])
        t["adj_profit"] = -(t["profit"] or 0) if inv else (t["profit"] or 0)
        t["is_inverse"] = inv
        t["session"] = "RTH" if is_rth(t["instrument"], t["entryTime"]) else "ETH"
        trades.append(t)

    strats = defaultdict(list)
    for t in trades:
        strats[t["strategy"]].append(t)

    sorted_strats = sorted(strats.items(), key=lambda x: sum(t["adj_profit"] for t in x[1]), reverse=True)

    # ======== SECTION 1: Symbol x Direction per strategy ========
    print("=" * 140)
    print(f"{'SECTION 1: SYMBOL x DIRECTION BREAKDOWN PER STRATEGY':^140}")
    print("=" * 140)

    for strat_name, strat_trades in sorted_strats:
        total_pnl = sum(t["adj_profit"] for t in strat_trades)
        days = len(set(t["entryDate"] for t in strat_trades))
        inv_tag = " [INV]" if is_inverse(strat_name) else ""
        print(f"\n{'~' * 140}")
        print(f"  {strat_name}{inv_tag}  --  {len(strat_trades)} trades, {days} days, ${total_pnl:>+,.2f}")
        print(f"{'~' * 140}")
        print(f"  {'Symbol':<6s} {'Dir':<6s} {'Trades':>6s} {'P/L':>12s} {'WR':>7s} {'PF':>7s} {'AvgWin':>10s} {'AvgLoss':>10s} {'$/Trade':>10s}  Verdict")
        print(f"  {'-'*6} {'-'*6} {'-'*6} {'-'*12} {'-'*7} {'-'*7} {'-'*10} {'-'*10} {'-'*10}  {'-'*12}")

        # Group by instrument + direction
        combos = defaultdict(list)
        for t in strat_trades:
            combos[(t["instrument"], t["direction"])].append(t)

        combo_stats = []
        for (inst, dirn), grp in sorted(combos.items()):
            s = analyze_group(grp)
            if s:
                combo_stats.append((inst, dirn, s, grp))

        # Sort by P/L
        combo_stats.sort(key=lambda x: x[2]["pnl"], reverse=True)

        for inst, dirn, s, grp in combo_stats:
            per_trade = s["pnl"] / s["n"]
            # Verdict
            if s["n"] < 5:
                verdict = "LOW SAMPLE"
            elif s["pf"] >= 1.3 and s["wr"] >= 45:
                verdict = "++ KEEP"
            elif s["pf"] >= 1.1 and s["wr"] >= 45:
                verdict = "+  KEEP"
            elif s["pf"] >= 0.95 and s["pf"] <= 1.05:
                verdict = "~  MARGINAL"
            elif s["pf"] < 0.8:
                verdict = "-- DROP"
            elif s["pf"] < 0.95:
                verdict = "-  WEAK"
            else:
                verdict = "   OK"
            print(f"  {inst:<6s} {dirn:<6s} {s['n']:>6d} ${s['pnl']:>+10,.2f} {s['wr']:>6.1f}% {s['pf']:>6.2f} ${s['avg_w']:>9,.2f} ${s['avg_l']:>9,.2f} ${per_trade:>9,.2f}  {verdict}")

    # ======== SECTION 2: RTH vs ETH per strategy ========
    print(f"\n\n{'=' * 140}")
    print(f"{'SECTION 2: RTH vs ETH (OVERNIGHT/GLOBEX) PER STRATEGY':^140}")
    print("=" * 140)

    print(f"\n  {'Strategy':<25s} {'':>5s} {'RTH Trades':>10s} {'RTH P/L':>12s} {'RTH WR':>7s} {'RTH PF':>7s} {'|':>2s} {'ETH Trades':>10s} {'ETH P/L':>12s} {'ETH WR':>7s} {'ETH PF':>7s} {'|':>2s} {'Recommendation'}")
    print(f"  {'-' * 130}")

    for strat_name, strat_trades in sorted_strats:
        inv_tag = " [I]" if is_inverse(strat_name) else ""
        label = strat_name + inv_tag

        rth = [t for t in strat_trades if t["session"] == "RTH"]
        eth = [t for t in strat_trades if t["session"] == "ETH"]

        rs = analyze_group(rth) if rth else None
        es = analyze_group(eth) if eth else None

        rth_str = f"{rs['n']:>10d} ${rs['pnl']:>+10,.0f} {rs['wr']:>6.1f}% {rs['pf']:>6.2f}" if rs else f"{'--':>10s} {'--':>12s} {'--':>7s} {'--':>7s}"
        eth_str = f"{es['n']:>10d} ${es['pnl']:>+10,.0f} {es['wr']:>6.1f}% {es['pf']:>6.2f}" if es else f"{'--':>10s} {'--':>12s} {'--':>7s} {'--':>7s}"

        # Recommendation
        rec = ""
        if rs and es:
            if rs["pf"] >= 1.1 and es["pf"] < 0.95 and es["n"] >= 10:
                rec = ">>> RTH ONLY"
            elif es["pf"] >= 1.1 and rs["pf"] < 0.95 and rs["n"] >= 10:
                rec = ">>> ETH ONLY"
            elif rs["pf"] >= 1.1 and es["pf"] >= 1.1:
                rec = "Both good"
            elif rs["pf"] < 0.95 and es["pf"] < 0.95:
                rec = "Both weak"
            elif rs["pf"] >= 1.1 and es["pf"] < 1.1:
                rec = "RTH better"
            elif es["pf"] >= 1.1 and rs["pf"] < 1.1:
                rec = "ETH better"
            else:
                rec = ""
        elif rs and not es:
            rec = "RTH only (no ETH data)"
        elif es and not rs:
            rec = "ETH only (no RTH data)"

        print(f"  {label:<25s} {'':<5s} {rth_str} {'|':>2s} {eth_str} {'|':>2s} {rec}")

    # ======== SECTION 2b: RTH vs ETH by symbol within each strategy ========
    print(f"\n\n{'=' * 140}")
    print(f"{'SECTION 2b: RTH vs ETH BROKEN DOWN BY SYMBOL (strategies with mixed results)':^140}")
    print("=" * 140)

    for strat_name, strat_trades in sorted_strats:
        rth_all = [t for t in strat_trades if t["session"] == "RTH"]
        eth_all = [t for t in strat_trades if t["session"] == "ETH"]
        rs_all = analyze_group(rth_all) if rth_all else None
        es_all = analyze_group(eth_all) if eth_all else None

        # Only show strategies where there's a meaningful split
        if not rs_all or not es_all:
            continue
        if rs_all["n"] < 10 or es_all["n"] < 10:
            continue

        inv_tag = " [INV]" if is_inverse(strat_name) else ""
        print(f"\n  {strat_name}{inv_tag}:")
        print(f"    {'Symbol':<6s} {'RTH#':>5s} {'RTH P/L':>10s} {'RTH WR':>7s} {'RTH PF':>7s} {'|':>2s} {'ETH#':>5s} {'ETH P/L':>10s} {'ETH WR':>7s} {'ETH PF':>7s}")
        print(f"    {'-'*80}")

        instruments = sorted(set(t["instrument"] for t in strat_trades))
        for inst in instruments:
            r_grp = [t for t in strat_trades if t["instrument"] == inst and t["session"] == "RTH"]
            e_grp = [t for t in strat_trades if t["instrument"] == inst and t["session"] == "ETH"]
            r = analyze_group(r_grp) if r_grp else None
            e = analyze_group(e_grp) if e_grp else None
            r_str = f"{r['n']:>5d} ${r['pnl']:>+8,.0f} {r['wr']:>6.1f}% {r['pf']:>6.2f}" if r else f"{'--':>5s} {'--':>10s} {'--':>7s} {'--':>7s}"
            e_str = f"{e['n']:>5d} ${e['pnl']:>+8,.0f} {e['wr']:>6.1f}% {e['pf']:>6.2f}" if e else f"{'--':>5s} {'--':>10s} {'--':>7s} {'--':>7s}"
            print(f"    {inst:<6s} {r_str} {'|':>2s} {e_str}")

    # ======== SECTION 3: Should you STOP inversing? ========
    print(f"\n\n{'=' * 140}")
    print(f"{'SECTION 3: INVERSE AUDIT -- Should you STOP inversing any of these?':^140}")
    print(f"{'(Showing P/L as ORIGINAL direction, then as INVERSED)':^140}")
    print("=" * 140)

    inv_strats = [(sn, st) for sn, st in sorted_strats if is_inverse(sn)]
    print(f"\n  {'Strategy':<25s} {'Trades':>7s} {'|':>2s} {'Original P/L':>12s} {'Orig PF':>8s} {'|':>2s} {'Inversed P/L':>12s} {'Inv PF':>8s} {'|':>2s} {'Recommendation'}")
    print(f"  {'-' * 110}")

    for strat_name, strat_trades in inv_strats:
        # adj_profit is already inversed, so original = -adj_profit
        inv_profits = [t["adj_profit"] for t in strat_trades]
        orig_profits = [-p for p in inv_profits]

        inv_total = sum(inv_profits)
        orig_total = sum(orig_profits)

        inv_w = [p for p in inv_profits if p > 0]
        inv_l = [p for p in inv_profits if p < 0]
        orig_w = [p for p in orig_profits if p > 0]
        orig_l = [p for p in orig_profits if p < 0]

        inv_pf = pf(inv_w, inv_l)
        orig_pf = pf(orig_w, orig_l)

        if inv_pf > 1.1 and orig_pf < 0.95:
            rec = "KEEP INVERSING"
        elif orig_pf > 1.1 and inv_pf < 0.95:
            rec = ">>> STOP INVERSING"
        elif inv_pf > orig_pf and inv_pf > 1.0:
            rec = "Keep inversing (slight edge)"
        elif orig_pf > inv_pf and orig_pf > 1.0:
            rec = ">> Consider stopping"
        else:
            rec = "Neither direction works well"

        print(f"  {strat_name:<25s} {len(strat_trades):>7d} {'|':>2s} ${orig_total:>+11,.2f} {orig_pf:>7.2f} {'|':>2s} ${inv_total:>+11,.2f} {inv_pf:>7.2f} {'|':>2s} {rec}")

        # Per-symbol breakdown for inverse strategies
        inst_combos = defaultdict(list)
        for t in strat_trades:
            inst_combos[t["instrument"]].append(t)

        for inst in sorted(inst_combos.keys()):
            grp = inst_combos[inst]
            ip = [t["adj_profit"] for t in grp]
            op = [-p for p in ip]
            i_w = [p for p in ip if p > 0]
            i_l = [p for p in ip if p < 0]
            o_w = [p for p in op if p > 0]
            o_l = [p for p in op if p < 0]
            ipf = pf(i_w, i_l)
            opf = pf(o_w, o_l)
            flag = ""
            if opf > 1.15 and ipf < 0.9 and len(grp) >= 10:
                flag = " <<< STOP INV THIS SYMBOL"
            elif ipf > 1.15 and opf < 0.9 and len(grp) >= 10:
                flag = " (good inverse)"
            print(f"    {inst:<6s} {len(grp):>5d}t  |  orig=${sum(op):>+8,.0f} PF={opf:.2f}  |  inv=${sum(ip):>+8,.0f} PF={ipf:.2f}{flag}")

    # ======== SECTION 4: Should you START inversing? ========
    print(f"\n\n{'=' * 140}")
    print(f"{'SECTION 4: NON-INVERSE STRATEGIES -- Should you START inversing any?':^140}")
    print(f"{'(Checking if flipping would improve results)':^140}")
    print("=" * 140)

    non_inv = [(sn, st) for sn, st in sorted_strats if not is_inverse(sn)]
    print(f"\n  {'Strategy':<25s} {'Trades':>7s} {'|':>2s} {'Current P/L':>12s} {'Cur PF':>8s} {'|':>2s} {'If Inversed':>12s} {'Inv PF':>8s} {'|':>2s} {'Recommendation'}")
    print(f"  {'-' * 110}")

    for strat_name, strat_trades in non_inv:
        cur_profits = [t["adj_profit"] for t in strat_trades]
        flip_profits = [-p for p in cur_profits]

        cur_total = sum(cur_profits)
        flip_total = sum(flip_profits)

        cur_w = [p for p in cur_profits if p > 0]
        cur_l = [p for p in cur_profits if p < 0]
        flip_w = [p for p in flip_profits if p > 0]
        flip_l = [p for p in flip_profits if p < 0]

        cur_pf = pf(cur_w, cur_l)
        flip_pf = pf(flip_w, flip_l)

        days = len(set(t["entryDate"] for t in strat_trades))

        if cur_pf >= 1.1:
            rec = "Keep as-is (profitable)"
        elif cur_pf < 0.85 and flip_pf > 1.15 and len(strat_trades) >= 20:
            rec = ">>> CONSIDER INVERSING"
        elif cur_pf < 0.9 and flip_pf > 1.1 and len(strat_trades) >= 20:
            rec = ">> Inversing looks better"
        elif cur_pf < 0.95 and flip_pf > 1.05 and len(strat_trades) >= 20:
            rec = "> Slight inverse edge"
        elif cur_pf < 0.95 and flip_pf < 0.95:
            rec = "Neither direction works"
        else:
            rec = ""

        print(f"  {strat_name:<25s} {len(strat_trades):>7d} {'|':>2s} ${cur_total:>+11,.2f} {cur_pf:>7.2f} {'|':>2s} ${flip_total:>+11,.2f} {flip_pf:>7.2f} {'|':>2s} {rec}")

        # Per-symbol if the strategy is losing
        if cur_pf < 1.0 and len(strat_trades) >= 15:
            inst_combos = defaultdict(list)
            for t in strat_trades:
                inst_combos[t["instrument"]].append(t)
            for inst in sorted(inst_combos.keys()):
                grp = inst_combos[inst]
                cp = [t["adj_profit"] for t in grp]
                fp = [-p for p in cp]
                c_w = [p for p in cp if p > 0]
                c_l = [p for p in cp if p < 0]
                f_w = [p for p in fp if p > 0]
                f_l = [p for p in fp if p < 0]
                cpf = pf(c_w, c_l)
                fpf = pf(f_w, f_l)
                flag = ""
                if cpf < 0.85 and fpf > 1.15 and len(grp) >= 8:
                    flag = " <<< INVERSE THIS SYMBOL"
                elif cpf < 0.9 and fpf > 1.1 and len(grp) >= 8:
                    flag = " << consider inversing"
                print(f"    {inst:<6s} {len(grp):>5d}t  |  cur=${sum(cp):>+8,.0f} PF={cpf:.2f}  |  inv=${sum(fp):>+8,.0f} PF={fpf:.2f}{flag}")

    # ======== SECTION 5: OPTIMAL SYMBOL/DIRECTION MATRIX ========
    print(f"\n\n{'=' * 140}")
    print(f"{'SECTION 5: OPTIMAL CONFIG MATRIX -- What to trade, where, when':^140}")
    print("=" * 140)

    print(f"\n  Criteria: PF >= 1.15, >= 10 trades, showing best combos\n")
    print(f"  {'Strategy':<22s} {'Symbol':<6s} {'Dir':<6s} {'Session':<8s} {'Trades':>6s} {'P/L':>10s} {'WR':>6s} {'PF':>6s} {'$/Trade':>9s}")
    print(f"  {'-' * 90}")

    winners = []
    for strat_name, strat_trades in sorted_strats:
        combos = defaultdict(list)
        for t in strat_trades:
            combos[(t["instrument"], t["direction"], t["session"])].append(t)

        for (inst, dirn, sess), grp in combos.items():
            s = analyze_group(grp)
            if s and s["n"] >= 10 and s["pf"] >= 1.15:
                winners.append((strat_name, inst, dirn, sess, s))

    winners.sort(key=lambda x: x[4]["pnl"], reverse=True)
    for sn, inst, dirn, sess, s in winners:
        inv_tag = "*" if is_inverse(sn) else ""
        per = s["pnl"] / s["n"]
        print(f"  {sn+inv_tag:<22s} {inst:<6s} {dirn:<6s} {sess:<8s} {s['n']:>6d} ${s['pnl']:>+8,.0f} {s['wr']:>5.1f}% {s['pf']:>5.2f} ${per:>8,.2f}")

    print(f"\n  * = inversed strategy")

    # Also show the worst combos (to avoid)
    print(f"\n\n  WORST COMBOS (PF < 0.80, >= 10 trades):\n")
    print(f"  {'Strategy':<22s} {'Symbol':<6s} {'Dir':<6s} {'Session':<8s} {'Trades':>6s} {'P/L':>10s} {'WR':>6s} {'PF':>6s} {'$/Trade':>9s}")
    print(f"  {'-' * 90}")

    losers_list = []
    for strat_name, strat_trades in sorted_strats:
        combos = defaultdict(list)
        for t in strat_trades:
            combos[(t["instrument"], t["direction"], t["session"])].append(t)

        for (inst, dirn, sess), grp in combos.items():
            s = analyze_group(grp)
            if s and s["n"] >= 10 and s["pf"] < 0.80:
                losers_list.append((strat_name, inst, dirn, sess, s))

    losers_list.sort(key=lambda x: x[4]["pnl"])
    for sn, inst, dirn, sess, s in losers_list:
        inv_tag = "*" if is_inverse(sn) else ""
        per = s["pnl"] / s["n"]
        print(f"  {sn+inv_tag:<22s} {inst:<6s} {dirn:<6s} {sess:<8s} {s['n']:>6d} ${s['pnl']:>+8,.0f} {s['wr']:>5.1f}% {s['pf']:>5.2f} ${per:>8,.2f}")


if __name__ == "__main__":
    main()
