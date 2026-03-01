"""Today's trade analysis with full adjustments."""
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime

DB = r"D:\futures\edge\zenbot-edge\data\trades.db"
TODAY = "2026-02-27"
EXCLUDE_PREFIXES = ["APEX","TDFY","TDY","TPT","PA","LTE","FTDY","ftd","BX","CHB","BLU","sim101"]
PORTFOLIO = {"ES","MES","NQ","MNQ","GC","MGC","RTY","M2K","YM","MYM","CL","MCL"}

RTH_WINDOWS = {
    "ES": (570, 960), "MES": (570, 960),
    "NQ": (570, 960), "MNQ": (570, 960),
    "RTY": (570, 960), "M2K": (570, 960),
    "YM": (570, 960), "MYM": (570, 960),
    "CL": (540, 870), "MCL": (540, 870),
    "GC": (500, 810), "MGC": (500, 810),
}

def is_inverse(strat):
    s = strat.lower()
    return "inv" in s or s in ("ema-runner", "ema-runner-ah")

def is_excluded(strat):
    return any(strat.startswith(p) for p in EXCLUDE_PREFIXES) or any(strat.lower().startswith(p.lower()) for p in EXCLUDE_PREFIXES)

def pf(wins, losses):
    gw = sum(wins)
    gl = abs(sum(losses))
    if gl == 0: return float("inf") if gw > 0 else 0
    return gw / gl

def is_rth(entry_time_str, instrument):
    try:
        if "T" in entry_time_str:
            dt = datetime.fromisoformat(entry_time_str)
        elif "AM" in entry_time_str or "PM" in entry_time_str:
            dt = datetime.strptime(entry_time_str, "%m/%d/%Y %I:%M:%S %p")
        else:
            dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
        mins = dt.hour * 60 + dt.minute
        window = RTH_WINDOWS.get(instrument, (570, 960))
        return window[0] <= mins < window[1]
    except:
        return None

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM trades WHERE entryDate = ? ORDER BY strategy, entryTime", (TODAY,))
    all_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Filter: portfolio instruments only, exclude follower accounts
    trades = [t for t in all_rows if t["instrument"] in PORTFOLIO and not is_excluded(t["strategy"])]

    # Apply inverse flip
    for t in trades:
        if is_inverse(t["strategy"]):
            t["profit"] = -(t["profit"] or 0)
            orig_mae, orig_mfe = (t["mae"] or 0), (t["mfe"] or 0)
            t["mae"] = orig_mfe
            t["mfe"] = orig_mae

    total_trades = len(trades)
    total_pnl = sum(t["profit"] or 0 for t in trades)
    total_raw = len(all_rows)

    print("=" * 140)
    print(f"{'ZENBOT EDGE -- TODAY ' + TODAY:^140}")
    print(f"{str(total_trades) + ' portfolio trades (' + str(total_raw) + ' raw) | P/L: $' + f'{total_pnl:+,.2f}':^140}")
    print("=" * 140)

    # ===== STRATEGY SUMMARY =====
    strats = defaultdict(list)
    for t in trades:
        strats[t["strategy"]].append(t)

    results = []
    for sn, tlist in strats.items():
        profits = [t["profit"] or 0 for t in tlist]
        total = sum(profits)
        winners = [p for p in profits if p > 0]
        losers = [p for p in profits if p < 0]
        wr = len(winners) / len(tlist) * 100
        pf_val = pf(winners, losers)
        avg = statistics.mean(profits)
        inv = is_inverse(sn)

        # By instrument
        inst_map = defaultdict(list)
        for t in tlist:
            inst_map[t["instrument"]].append(t["profit"] or 0)

        # By direction
        long_pnl = sum(t["profit"] or 0 for t in tlist if t["direction"] == "Long")
        short_pnl = sum(t["profit"] or 0 for t in tlist if t["direction"] == "Short")
        long_n = sum(1 for t in tlist if t["direction"] == "Long")
        short_n = sum(1 for t in tlist if t["direction"] == "Short")

        # RTH vs ETH
        rth_t = [t for t in tlist if is_rth(t["entryTime"] or "", t["instrument"]) is True]
        eth_t = [t for t in tlist if is_rth(t["entryTime"] or "", t["instrument"]) is False]
        rth_pnl = sum(t["profit"] or 0 for t in rth_t)
        eth_pnl = sum(t["profit"] or 0 for t in eth_t)

        results.append({
            "name": sn, "n": len(tlist), "pnl": total, "wr": wr, "pf": pf_val,
            "avg": avg, "inv": inv, "inst_map": inst_map,
            "long_pnl": long_pnl, "short_pnl": short_pnl,
            "long_n": long_n, "short_n": short_n,
            "rth_pnl": rth_pnl, "eth_pnl": eth_pnl,
            "rth_n": len(rth_t), "eth_n": len(eth_t),
            "trades": tlist,
        })

    results.sort(key=lambda x: x["pnl"], reverse=True)

    print(f"\n  {'Strategy':<22s} {'Inv':>4s} {'N':>5s} {'P/L':>12s} {'WR':>6s} {'PF':>6s} {'$/Trade':>9s} {'Long P/L':>10s} {'Short P/L':>10s} {'RTH P/L':>9s} {'ETH P/L':>9s}")
    print(f"  {'-' * 120}")

    for r in results:
        inv_tag = "INV" if r["inv"] else ""
        print(f"  {r['name']:<22s} {inv_tag:>4s} {r['n']:>5d} ${r['pnl']:>+10,.2f} {r['wr']:>5.1f}% {r['pf']:>5.2f} ${r['avg']:>+7,.2f} ${r['long_pnl']:>+8,.0f}({r['long_n']}) ${r['short_pnl']:>+8,.0f}({r['short_n']}) ${r['rth_pnl']:>+7,.0f} ${r['eth_pnl']:>+7,.0f}")

    # Totals
    total_long = sum(r["long_pnl"] for r in results)
    total_short = sum(r["short_pnl"] for r in results)
    total_long_n = sum(r["long_n"] for r in results)
    total_short_n = sum(r["short_n"] for r in results)
    total_rth = sum(r["rth_pnl"] for r in results)
    total_eth = sum(r["eth_pnl"] for r in results)
    print(f"  {'-' * 120}")
    print(f"  {'TOTAL':<22s}      {total_trades:>5d} ${total_pnl:>+10,.2f}                           ${total_long:>+8,.0f}({total_long_n}) ${total_short:>+8,.0f}({total_short_n}) ${total_rth:>+7,.0f} ${total_eth:>+7,.0f}")

    # ===== BY INSTRUMENT =====
    print(f"\n\n{'=' * 140}")
    print(f"{'BY INSTRUMENT':^140}")
    print(f"{'=' * 140}")

    inst_all = defaultdict(list)
    for t in trades:
        inst_all[t["instrument"]].append(t)

    print(f"\n  {'Instrument':<10s} {'N':>5s} {'P/L':>12s} {'WR':>6s} {'PF':>6s} {'Long P/L':>10s} {'Short P/L':>10s} {'Long WR':>8s} {'Short WR':>9s}")
    print(f"  {'-' * 85}")

    for inst in sorted(inst_all.keys()):
        tl = inst_all[inst]
        profs = [t["profit"] or 0 for t in tl]
        total = sum(profs)
        w = [p for p in profs if p > 0]
        l = [p for p in profs if p < 0]
        wr = len(w) / len(tl) * 100
        pf_val = pf(w, l)

        longs = [t for t in tl if t["direction"] == "Long"]
        shorts = [t for t in tl if t["direction"] == "Short"]
        long_pnl = sum(t["profit"] or 0 for t in longs)
        short_pnl = sum(t["profit"] or 0 for t in shorts)
        long_wr = sum(1 for t in longs if (t["profit"] or 0) > 0) / len(longs) * 100 if longs else 0
        short_wr = sum(1 for t in shorts if (t["profit"] or 0) > 0) / len(shorts) * 100 if shorts else 0

        print(f"  {inst:<10s} {len(tl):>5d} ${total:>+10,.2f} {wr:>5.1f}% {pf_val:>5.2f} ${long_pnl:>+8,.0f}({len(longs)}) ${short_pnl:>+8,.0f}({len(shorts)}) {long_wr:>6.1f}% {short_wr:>7.1f}%")

    # ===== BY INSTRUMENT x DIRECTION x STRATEGY =====
    print(f"\n\n{'=' * 140}")
    print(f"{'INSTRUMENT x DIRECTION DETAIL (by strategy)':^140}")
    print(f"{'=' * 140}")

    for inst in sorted(inst_all.keys()):
        for direction in ["Long", "Short"]:
            combo_trades = [t for t in trades if t["instrument"] == inst and t["direction"] == direction]
            if not combo_trades:
                continue
            combo_pnl = sum(t["profit"] or 0 for t in combo_trades)
            combo_wr = sum(1 for t in combo_trades if (t["profit"] or 0) > 0) / len(combo_trades) * 100

            print(f"\n  {inst} {direction}: {len(combo_trades)} trades, ${combo_pnl:>+,.2f}, WR={combo_wr:.1f}%")

            # Per strategy
            strat_combo = defaultdict(list)
            for t in combo_trades:
                strat_combo[t["strategy"]].append(t["profit"] or 0)

            for sn in sorted(strat_combo.keys(), key=lambda s: sum(strat_combo[s]), reverse=True):
                profs = strat_combo[sn]
                total = sum(profs)
                wr = sum(1 for p in profs if p > 0) / len(profs) * 100
                inv_tag = " [INV]" if is_inverse(sn) else ""
                print(f"    {sn}{inv_tag}: {len(profs)} trades, ${total:>+,.2f}, WR={wr:.1f}%")

    # ===== TOP WINNERS & LOSERS =====
    print(f"\n\n{'=' * 140}")
    print(f"{'TOP 15 WINNERS':^140}")
    print(f"{'=' * 140}")

    sorted_by_profit = sorted(trades, key=lambda t: t["profit"] or 0, reverse=True)

    print(f"\n  {'Strategy':<22s} {'Inst':>5s} {'Dir':>6s} {'P/L':>10s} {'MAE':>8s} {'MFE':>8s} {'Hold':>6s} {'Entry Time'}")
    print(f"  {'-' * 95}")
    for t in sorted_by_profit[:15]:
        inv_tag = "*" if is_inverse(t["strategy"]) else ""
        hold = f"{t['holdingMinutes'] or 0:.0f}m"
        entry = t["entryTime"] or ""
        if "T" in entry:
            entry = entry[11:16]
        elif len(entry) > 10:
            entry = entry[11:16] if " " in entry else entry
        print(f"  {t['strategy']}{inv_tag:<22s} {t['instrument']:>5s} {t['direction']:>6s} ${(t['profit'] or 0):>+8,.2f} ${(t['mae'] or 0):>6,.0f} ${(t['mfe'] or 0):>6,.0f} {hold:>6s} {entry}")

    print(f"\n\n{'=' * 140}")
    print(f"{'TOP 15 LOSERS':^140}")
    print(f"{'=' * 140}")

    print(f"\n  {'Strategy':<22s} {'Inst':>5s} {'Dir':>6s} {'P/L':>10s} {'MAE':>8s} {'MFE':>8s} {'Hold':>6s} {'Entry Time'}")
    print(f"  {'-' * 95}")
    for t in sorted_by_profit[-15:]:
        inv_tag = "*" if is_inverse(t["strategy"]) else ""
        hold = f"{t['holdingMinutes'] or 0:.0f}m"
        entry = t["entryTime"] or ""
        if "T" in entry:
            entry = entry[11:16]
        elif len(entry) > 10:
            entry = entry[11:16] if " " in entry else entry
        print(f"  {t['strategy']}{inv_tag:<22s} {t['instrument']:>5s} {t['direction']:>6s} ${(t['profit'] or 0):>+8,.2f} ${(t['mae'] or 0):>6,.0f} ${(t['mfe'] or 0):>6,.0f} {hold:>6s} {entry}")

    # ===== TIME OF DAY =====
    print(f"\n\n{'=' * 140}")
    print(f"{'TIME OF DAY':^140}")
    print(f"{'=' * 140}")

    hh_map = defaultdict(list)
    for t in trades:
        hh_map[t["entryHalfHour"] or "unknown"].append(t["profit"] or 0)

    print(f"\n  {'Time':>8s} {'Trades':>7s} {'P/L':>12s} {'WR':>7s} {'PF':>7s} {'$/Trade':>10s}")
    print(f"  {'-' * 60}")
    for hh in sorted(hh_map.keys()):
        profs = hh_map[hh]
        total = sum(profs)
        wr = sum(1 for p in profs if p > 0) / len(profs) * 100
        avg = statistics.mean(profs)
        w = [p for p in profs if p > 0]
        l = [p for p in profs if p < 0]
        pf_val = pf(w, l)
        bar = "+" * max(0, int(total / 300)) if total > 0 else "-" * max(0, int(-total / 300))
        print(f"  {hh:>8s} {len(profs):>7d} ${total:>+10,.2f} {wr:>6.1f}% {pf_val:>6.2f} ${avg:>+8,.2f}  {bar}")

    # ===== TRADE EFFICIENCY =====
    print(f"\n\n{'=' * 140}")
    print(f"{'TRADE EFFICIENCY (avg MAE/MFE/ETD by strategy)':^140}")
    print(f"{'=' * 140}")

    print(f"\n  {'Strategy':<22s} {'N':>5s} {'P/L':>12s} {'AvgMAE':>9s} {'AvgMFE':>9s} {'AvgETD':>9s} {'MFE/MAE':>8s} {'Capture%':>9s}")
    print(f"  {'-' * 95}")

    for r in results:
        tl = r["trades"]
        maes = [t["mae"] or 0 for t in tl if t["mae"] is not None]
        mfes = [t["mfe"] or 0 for t in tl if t["mfe"] is not None]
        etds = [t["etd"] or 0 for t in tl if t["etd"] is not None]
        avg_mae = statistics.mean(maes) if maes else 0
        avg_mfe = statistics.mean(mfes) if mfes else 0
        avg_etd = statistics.mean(etds) if etds else 0
        mfe_mae = avg_mfe / avg_mae if avg_mae > 0 else 0
        capture = (r["avg"] / avg_mfe * 100) if avg_mfe > 0 else 0
        print(f"  {r['name']:<22s} {r['n']:>5d} ${r['pnl']:>+10,.2f} ${avg_mae:>7,.0f} ${avg_mfe:>7,.0f} ${avg_etd:>7,.0f} {mfe_mae:>7.2f} {capture:>8.1f}%")


if __name__ == "__main__":
    main()
