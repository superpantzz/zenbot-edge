"""Export full strategy x instrument x direction matrix to CSV for Excel."""
import csv
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime

DB = r"D:\futures\edge\zenbot-edge\data\trades.db"
OUT = r"C:\projects\futures-analysis\strategy_matrix.csv"
EXCLUDE_PREFIXES = ["APEX","TDFY","TDY","TPT","PA","LTE","FTDY","ftd","BX","CHB","BLU","sim101"]
VALID = {"ES","MES","NQ","MNQ","GC","MGC","RTY","M2K","YM","MYM","CL","MCL"}

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
        return round(gw, 2) if gw > 0 else 0  # avoid inf in CSV
    return round(gw / gl, 4)

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

def metrics(trades):
    """Compute metrics for a group of trades. Returns dict."""
    if not trades:
        return None
    profits = [t["profit"] or 0 for t in trades]
    n = len(trades)
    total = sum(profits)
    days = len(set(t["entryDate"] for t in trades))
    w = [p for p in profits if p > 0]
    l = [p for p in profits if p < 0]
    wr = round(len(w) / n * 100, 2) if n else 0
    pf_val = pf(w, l)
    inv_w = [-p for p in l]
    inv_l = [-p for p in w]
    inv_pf_val = pf(inv_w, inv_l)
    avg_trade = round(total / n, 2) if n else 0
    avg_w = round(statistics.mean(w), 2) if w else 0
    avg_l = round(statistics.mean(l), 2) if l else 0
    avg_mae = round(statistics.mean([t["mae"] or 0 for t in trades]), 2)
    avg_mfe = round(statistics.mean([t["mfe"] or 0 for t in trades]), 2)
    avg_hold = round(statistics.mean([t["holdingMinutes"] or 0 for t in trades]), 1)
    first = min(t["entryDate"] for t in trades)
    last = max(t["entryDate"] for t in trades)
    return {
        "n": n, "days": days, "pnl": round(total, 2), "wr": wr,
        "pf": pf_val, "inv_pf": inv_pf_val,
        "avg_trade": avg_trade, "avg_w": avg_w, "avg_l": avg_l,
        "avg_mae": avg_mae, "avg_mfe": avg_mfe, "avg_hold": avg_hold,
        "first": first, "last": last,
    }

def rate(m, is_inv):
    """Rate a combo based on metrics. Uses best-direction PF."""
    if m is None:
        return ""
    best_pf = max(m["pf"], m["inv_pf"])
    best_dir = "ORIGINAL" if m["pf"] >= m["inv_pf"] else "INVERSE"
    # If strategy is already inversed, "ORIGINAL" means we keep the inversion
    n, days = m["n"], m["days"]
    if best_pf >= 1.5 and n >= 30 and days >= 15:
        return "STRONG EDGE"
    if best_pf >= 1.3 and n >= 30 and days >= 10:
        return "PROMISING"
    if best_pf >= 1.15 and n >= 20 and days >= 5:
        return "WORTH EXPLORING"
    if best_pf >= 1.05 and n >= 50:
        return "MARGINAL EDGE"
    if best_pf < 0.85 and m["pf"] < 0.85 and m["inv_pf"] < 0.85:
        return "NO EDGE"
    if n < 10:
        return "LOW SAMPLE"
    return "INCONCLUSIVE"

def confidence(m):
    if m is None:
        return ""
    best_pf = max(m["pf"], m["inv_pf"])
    n, days = m["n"], m["days"]
    if n >= 50 and days >= 20 and best_pf >= 1.3:
        return "HIGH"
    if n >= 25 and days >= 10 and best_pf >= 1.15:
        return "MEDIUM"
    if n >= 10 and best_pf >= 1.1:
        return "LOW"
    return "VERY LOW"

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT strategy, instrument, direction, profit, mae, mfe, etd,
               holdingMinutes, entryHour, entryHalfHour, entryDate, entryTime
        FROM trades
        ORDER BY strategy, entryTime
    """)
    all_trades = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Filter
    all_trades = [t for t in all_trades
                  if not is_excluded(t["strategy"]) and t["instrument"] in VALID]

    # Apply inverse flip
    for t in all_trades:
        if is_inverse(t["strategy"]):
            t["profit"] = -(t["profit"] or 0)
            orig_mae, orig_mfe = (t["mae"] or 0), (t["mfe"] or 0)
            t["mae"] = orig_mfe
            t["mfe"] = orig_mae

    rows = []

    # Group by strategy
    by_strat = defaultdict(list)
    for t in all_trades:
        by_strat[t["strategy"]].append(t)

    for strat_name in sorted(by_strat.keys()):
        strat_trades = by_strat[strat_name]
        inv_flag = is_inverse(strat_name)

        # Strategy-level overall
        m_all = metrics(strat_trades)
        if m_all is None or m_all["n"] < 5:
            continue

        best_dir_all = "ORIGINAL" if m_all["pf"] >= m_all["inv_pf"] else "INVERSE"
        best_pf_all = max(m_all["pf"], m_all["inv_pf"])
        best_pnl_all = m_all["pnl"] if best_dir_all == "ORIGINAL" else -m_all["pnl"]

        rows.append({
            "Strategy": strat_name,
            "Inversed": "YES" if inv_flag else "",
            "Instrument": "ALL",
            "Direction": "ALL",
            "Session": "ALL",
            "Trades": m_all["n"],
            "Days": m_all["days"],
            "P/L": m_all["pnl"],
            "WinRate%": m_all["wr"],
            "ProfitFactor": m_all["pf"],
            "InversePF": m_all["inv_pf"],
            "BestDirection": best_dir_all,
            "BestPF": best_pf_all,
            "BestP/L": best_pnl_all,
            "AvgTrade": m_all["avg_trade"],
            "AvgWin": m_all["avg_w"],
            "AvgLoss": m_all["avg_l"],
            "AvgMAE": m_all["avg_mae"],
            "AvgMFE": m_all["avg_mfe"],
            "AvgHoldMin": m_all["avg_hold"],
            "FirstDate": m_all["first"],
            "LastDate": m_all["last"],
            "Rating": rate(m_all, inv_flag),
            "Confidence": confidence(m_all),
            "RTH_Trades": "",
            "RTH_P/L": "",
            "RTH_PF": "",
            "ETH_Trades": "",
            "ETH_P/L": "",
            "ETH_PF": "",
            "RTH_Recommendation": "",
        })

        # By instrument x direction
        by_combo = defaultdict(list)
        for t in strat_trades:
            by_combo[(t["instrument"], t["direction"])].append(t)

        for (inst, dirn) in sorted(by_combo.keys()):
            combo_trades = by_combo[(inst, dirn)]
            m = metrics(combo_trades)
            if m is None or m["n"] < 3:
                continue

            best_dir = "ORIGINAL" if m["pf"] >= m["inv_pf"] else "INVERSE"
            best_pf_combo = max(m["pf"], m["inv_pf"])
            best_pnl_combo = m["pnl"] if best_dir == "ORIGINAL" else -m["pnl"]

            # RTH/ETH split
            rth_trades = [t for t in combo_trades if is_rth(t["instrument"], t["entryTime"] or "") is True]
            eth_trades = [t for t in combo_trades if is_rth(t["instrument"], t["entryTime"] or "") is False]
            m_rth = metrics(rth_trades) if len(rth_trades) >= 3 else None
            m_eth = metrics(eth_trades) if len(eth_trades) >= 3 else None

            rth_rec = ""
            if m_rth and m_eth:
                if m_rth["pf"] >= 1.15 and m_eth["pf"] < 0.90:
                    rth_rec = "RTH ONLY"
                elif m_eth["pf"] >= 1.15 and m_rth["pf"] < 0.90:
                    rth_rec = "ETH ONLY"
                elif m_rth["pf"] >= 1.15 and m_eth["pf"] >= 1.15:
                    rth_rec = "Both Good"
                elif m_rth["pf"] < 0.90 and m_eth["pf"] < 0.90:
                    rth_rec = "Both Weak"

            rows.append({
                "Strategy": strat_name,
                "Inversed": "YES" if inv_flag else "",
                "Instrument": inst,
                "Direction": dirn,
                "Session": "ALL",
                "Trades": m["n"],
                "Days": m["days"],
                "P/L": m["pnl"],
                "WinRate%": m["wr"],
                "ProfitFactor": m["pf"],
                "InversePF": m["inv_pf"],
                "BestDirection": best_dir,
                "BestPF": best_pf_combo,
                "BestP/L": best_pnl_combo,
                "AvgTrade": m["avg_trade"],
                "AvgWin": m["avg_w"],
                "AvgLoss": m["avg_l"],
                "AvgMAE": m["avg_mae"],
                "AvgMFE": m["avg_mfe"],
                "AvgHoldMin": m["avg_hold"],
                "FirstDate": m["first"],
                "LastDate": m["last"],
                "Rating": rate(m, inv_flag),
                "Confidence": confidence(m),
                "RTH_Trades": m_rth["n"] if m_rth else "",
                "RTH_P/L": m_rth["pnl"] if m_rth else "",
                "RTH_PF": m_rth["pf"] if m_rth else "",
                "ETH_Trades": m_eth["n"] if m_eth else "",
                "ETH_P/L": m_eth["pnl"] if m_eth else "",
                "ETH_PF": m_eth["pf"] if m_eth else "",
                "RTH_Recommendation": rth_rec,
            })

    # Write CSV
    fields = [
        "Strategy","Inversed","Instrument","Direction","Session",
        "Trades","Days","P/L","WinRate%","ProfitFactor","InversePF",
        "BestDirection","BestPF","BestP/L",
        "AvgTrade","AvgWin","AvgLoss","AvgMAE","AvgMFE","AvgHoldMin",
        "FirstDate","LastDate",
        "Rating","Confidence",
        "RTH_Trades","RTH_P/L","RTH_PF","ETH_Trades","ETH_P/L","ETH_PF",
        "RTH_Recommendation",
    ]

    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    total_rows = len(rows)
    strat_rows = sum(1 for r in rows if r["Instrument"] == "ALL")
    combo_rows = total_rows - strat_rows
    promising = sum(1 for r in rows if r["Rating"] in ("STRONG EDGE", "PROMISING", "WORTH EXPLORING"))
    print(f"Exported {total_rows} rows ({strat_rows} strategy summaries + {combo_rows} instrument/direction combos)")
    print(f"{promising} rows rated STRONG EDGE / PROMISING / WORTH EXPLORING")
    print(f"Saved to: {OUT}")


if __name__ == "__main__":
    main()
