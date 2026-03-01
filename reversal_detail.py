"""Detailed Reversal strategy analysis by symbol, direction, session."""
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime

DB = r"D:\futures\edge\zenbot-edge\data\trades.db"
EXCLUDE_PREFIXES = ["APEX","TDFY","TDY","TPT","PA","LTE","FTDY","ftd","BX","CHB","BLU","sim101"]
VALID = {"ES","MES","NQ","MNQ","GC","MGC","RTY","M2K","YM","MYM","CL","MCL"}

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

def analyze_group(label, trades):
    if not trades:
        return
    profits = [t["profit"] or 0 for t in trades]
    total = sum(profits)
    n = len(trades)
    days = len(set(t["entryDate"] for t in trades))
    w = [p for p in profits if p > 0]
    l = [p for p in profits if p < 0]
    wr = len(w) / n * 100
    pf_val = pf(w, l)
    inv_w = [-p for p in l]
    inv_l = [-p for p in w]
    inv_pf = pf(inv_w, inv_l)
    avg = statistics.mean(profits)
    avg_w = statistics.mean(w) if w else 0
    avg_l = statistics.mean(l) if l else 0
    first = min(t["entryDate"] for t in trades)
    last = max(t["entryDate"] for t in trades)
    print(f"  {label:<35s} {n:>5d}t {days:>4d}d ${total:>+10,.2f}  WR={wr:>5.1f}%  PF={pf_val:>5.2f}  InvPF={inv_pf:>5.2f}  AvgW=${avg_w:>+8,.2f}  AvgL=${avg_l:>+8,.2f}  $/t=${avg:>+7,.2f}  ({first} to {last})")

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT strategy, instrument, direction, profit, mae, mfe, etd,
               holdingMinutes, entryHour, entryHalfHour, entryDate, entryTime
        FROM trades
        WHERE LOWER(strategy) = 'reversal'
        ORDER BY entryTime
    """)
    all_trades = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Filter excluded accounts and non-portfolio instruments
    all_trades = [t for t in all_trades if not is_excluded(t["strategy"]) and t["instrument"] in VALID]

    print("=" * 150)
    print(f"{'REVERSAL STRATEGY -- COMPLETE BREAKDOWN':^150}")
    print(f"{'(' + str(len(all_trades)) + ' trades, portfolio instruments only)':^150}")
    print("=" * 150)

    # ========== OVERALL ==========
    print(f"\n--- OVERALL ---")
    analyze_group("ALL TRADES", all_trades)

    # ========== BY INSTRUMENT ==========
    print(f"\n\n{'=' * 150}")
    print(f"{'BY INSTRUMENT':^150}")
    print(f"{'=' * 150}")
    by_inst = defaultdict(list)
    for t in all_trades:
        by_inst[t["instrument"]].append(t)
    for inst in sorted(by_inst.keys(), key=lambda x: sum(t["profit"] or 0 for t in by_inst[x]), reverse=True):
        analyze_group(inst, by_inst[inst])

    # ========== BY INSTRUMENT x DIRECTION ==========
    print(f"\n\n{'=' * 150}")
    print(f"{'BY INSTRUMENT x DIRECTION':^150}")
    print(f"{'=' * 150}")
    by_combo = defaultdict(list)
    for t in all_trades:
        by_combo[(t["instrument"], t["direction"])].append(t)
    for combo in sorted(by_combo.keys(), key=lambda x: sum(t["profit"] or 0 for t in by_combo[x]), reverse=True):
        analyze_group(f"{combo[0]} {combo[1]}", by_combo[combo])

    # ========== BY INSTRUMENT x DIRECTION x SESSION ==========
    print(f"\n\n{'=' * 150}")
    print(f"{'BY INSTRUMENT x DIRECTION x SESSION':^150}")
    print(f"{'=' * 150}")
    by_full = defaultdict(list)
    for t in all_trades:
        rth = is_rth(t["instrument"], t["entryTime"] or "")
        sess = "RTH" if rth is True else ("ETH" if rth is False else "UNK")
        by_full[(t["instrument"], t["direction"], sess)].append(t)
    for combo in sorted(by_full.keys(), key=lambda x: sum(t["profit"] or 0 for t in by_full[x]), reverse=True):
        analyze_group(f"{combo[0]} {combo[1]} {combo[2]}", by_full[combo])

    # ========== TIME OF DAY BY INSTRUMENT ==========
    print(f"\n\n{'=' * 150}")
    print(f"{'TIME-OF-DAY BY INSTRUMENT (top instruments)':^150}")
    print(f"{'=' * 150}")

    for inst in ["NQ","MNQ","RTY","M2K","ES","MES","GC","MGC","YM","MYM","CL","MCL"]:
        inst_trades = by_inst.get(inst, [])
        if len(inst_trades) < 5:
            continue

        print(f"\n  --- {inst} ({len(inst_trades)} trades, ${sum(t['profit'] or 0 for t in inst_trades):>+,.2f}) ---")
        hh_map = defaultdict(list)
        for t in inst_trades:
            hh_map[t["entryHalfHour"] or "unknown"].append(t["profit"] or 0)

        print(f"  {'Time':>8s} {'N':>5s} {'P/L':>12s} {'WR':>7s} {'PF':>7s} {'$/Trade':>10s}")
        for hh in sorted(hh_map.keys()):
            profs = hh_map[hh]
            total = sum(profs)
            wr = sum(1 for p in profs if p > 0) / len(profs) * 100
            w = [p for p in profs if p > 0]
            l = [p for p in profs if p < 0]
            pf_val = pf(w, l)
            avg = statistics.mean(profs)
            bar = "+" * max(0, int(total / 200)) if total > 0 else "-" * max(0, int(-total / 200))
            print(f"  {hh:>8s} {len(profs):>5d} ${total:>+10,.2f} {wr:>6.1f}% {pf_val:>6.2f} ${avg:>+8,.2f}  {bar}")

    # ========== MONTHLY BY INSTRUMENT ==========
    print(f"\n\n{'=' * 150}")
    print(f"{'MONTHLY P/L BY INSTRUMENT':^150}")
    print(f"{'=' * 150}")

    for inst in ["NQ","MNQ","RTY","M2K","ES","MES","GC","MGC","YM","MYM","CL","MCL"]:
        inst_trades = by_inst.get(inst, [])
        if len(inst_trades) < 5:
            continue

        print(f"\n  --- {inst} ---")
        monthly = defaultdict(float)
        monthly_n = defaultdict(int)
        for t in inst_trades:
            m = t["entryDate"][:7]
            monthly[m] += (t["profit"] or 0)
            monthly_n[m] += 1
        cum = 0
        for m in sorted(monthly.keys()):
            cum += monthly[m]
            bar = "+" * max(0, int(monthly[m] / 200)) if monthly[m] > 0 else "-" * max(0, int(-monthly[m] / 200))
            print(f"    {m}: {monthly_n[m]:>3d}t ${monthly[m]:>+8,.0f}  (cum: ${cum:>+10,.0f})  {bar}")

    # ========== DIRECTION BREAKDOWN PER INSTRUMENT ==========
    print(f"\n\n{'=' * 150}")
    print(f"{'LONG vs SHORT PER INSTRUMENT -- ORIGINAL vs INVERSED':^150}")
    print(f"{'=' * 150}")

    print(f"\n  {'Inst+Dir':<15s} {'N':>5s} {'Days':>5s} {'Orig P/L':>12s} {'Orig PF':>8s} {'Orig WR':>8s} {'Inv P/L':>12s} {'Inv PF':>8s} {'Better':>10s} {'Confidence'}")
    print(f"  {'-' * 110}")

    for combo in sorted(by_combo.keys(), key=lambda x: (x[0], x[1])):
        trades = by_combo[combo]
        n = len(trades)
        if n < 3:
            continue
        days = len(set(t["entryDate"] for t in trades))
        profits = [t["profit"] or 0 for t in trades]
        total = sum(profits)
        w = [p for p in profits if p > 0]
        l = [p for p in profits if p < 0]
        wr = len(w) / n * 100
        pf_val = pf(w, l)
        inv_w = [-p for p in l]
        inv_l = [-p for p in w]
        inv_pf = pf(inv_w, inv_l)
        better = "ORIGINAL" if pf_val >= inv_pf else "INVERSE"
        better_pf = max(pf_val, inv_pf)
        conf = ""
        if n >= 30 and days >= 15 and better_pf >= 1.3:
            conf = "HIGH"
        elif n >= 15 and days >= 8 and better_pf >= 1.15:
            conf = "MEDIUM"
        elif n >= 8 and better_pf >= 1.1:
            conf = "LOW"
        else:
            conf = "VERY LOW"
        print(f"  {combo[0]+' '+combo[1]:<15s} {n:>5d} {days:>5d} ${total:>+10,.2f} {pf_val:>7.2f} {wr:>7.1f}% ${-total:>+10,.2f} {inv_pf:>7.2f} {better:>10s}  {conf}")


if __name__ == "__main__":
    main()
