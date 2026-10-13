#!/usr/bin/env python3
"""Score engine extraction results against the fixture-zero human reads.

Usage:
  python3 engine/score_pilot.py --results engine/out/results_<run>_<ver>.json \
      --humans corpus/fixture-zero/servers_read_v2.csv > pilot_scores.md

Scores five fields (cpu_model, ram_total_gb, price_usd, chassis_model,
listing_status) for every extracted listing. A field only counts when the human
read states it; "engine said null where human had a value" counts as a miss and
shows the raw title. Honest about ties/tolerances in the output.

ram_total_gb source preference (slice 3): when --ram-view-map is given, the
scorer prefers the schema view's deterministic aggregation
(`v_line_ram.ram_total_gb` — stated factors only, no LLM arithmetic) for the
ram_total_gb prediction, falling back to the engine attribute only when the
view yields NULL. The map is {item_id: ram_total_gb}, exported from the branch:

  psql "$DSN" -qAt -c "SELECT jsonb_object_agg(item_id, ram) FROM (
    SELECT p.payload->>'item_id' AS item_id, max(lr.ram_total_gb) AS ram
    FROM v_line_ram lr JOIN postings p ON p.id = lr.posting_id
    WHERE p.payload ? 'item_id' GROUP BY 1)" > ram_view_map.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys

FIELDS = ["cpu_model", "ram_total_gb", "price_usd", "chassis_model", "listing_status"]
AVAIL_MAP = {"available": "live", "unavailable": "ended"}


def norm_cpu(s):
    s = str(s).lower().strip()
    for w in ("amd ", "amd", "epyc", "intel", "xeon", "processor", "cpu"):
        s = s.replace(w, "")
    return re.sub(r"[^a-z0-9]", "", s)


def norm_chassis(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def to_num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def predicted(res: dict, ram_view: dict | None = None) -> dict:
    """Pull the five scored values out of one validated extraction result.

    ram_view (slice 3): {item_id: ram_total_gb} from the schema view
    v_line_ram (deterministic stated-factor aggregation). Preferred over the
    engine attribute — the view computes the total the engine correctly
    refuses to multiply; the attribute is the fallback when the view has no
    stated factors to aggregate (it yields NULL, never a guess).
    """
    out = {f: None for f in FIELDS}
    if not res or res.get("outcome") != "extracted" or not res.get("sale_groups"):
        return out
    g0 = res["sale_groups"][0]
    p = g0.get("price") or {}
    if p.get("amount") is not None:
        out["price_usd"] = to_num(p["amount"])
    elif p.get("bound_high") is not None:
        out["price_usd"] = to_num(p["bound_high"])
    out["listing_status"] = AVAIL_MAP.get(g0.get("availability"))
    attrs: dict = {}
    for ln in g0.get("lines", []):
        attrs.update(ln.get("attributes") or {})
    out["cpu_model"] = attrs.get("cpu_model")
    view_ram = (ram_view or {}).get(str(res.get("id")))
    if view_ram is not None:
        # the view aggregated stated factors — that is the honest deterministic
        # answer (a configured-server RAM line's stated_quantity may be the
        # per-config module count under a sold-out base config, so the engine
        # attribute can carry a partial-config product; the view's per-line
        # factors are the groundable value)
        out["ram_total_gb"] = to_num(view_ram)
    else:
        out["ram_total_gb"] = to_num(attrs.get("ram_total_gb"))
    out["chassis_model"] = attrs.get("chassis_model")
    return out


def human_row(row: dict) -> dict:
    return {
        "cpu_model": (row.get("cpu_model") or "").strip() or None,
        "ram_total_gb": to_num(row.get("ram_total_gb")),
        "price_usd": to_num(row.get("price_usd")),
        "chassis_model": (row.get("chassis_model") or "").strip() or None,
        "listing_status": (row.get("listing_status") or "").strip() or None,
    }


def score(results_path: str, humans_path: str, ram_view_path: str | None = None):
    with open(results_path) as f:
        run = json.load(f)
    ram_view = None
    if ram_view_path:
        with open(ram_view_path) as f:
            ram_view = json.load(f)
    quarantined = {str(r.get("id")) for r in run["results"]
                   if r and r.get("outcome") in ("quarantined", "no_purchase_information")}
    with open(humans_path, newline="") as f:
        humans = {str(r["item_id"]): r for r in csv.DictReader(f)}

    rows = []
    for res in run["results"]:
        rid = res.get("id")
        h = humans.get(str(rid))
        if not h:
            continue
        pred = predicted(res, ram_view)
        truth = human_row(h)
        rec = {"id": rid, "title": (h.get("title") or "")[:110],
               "quarantined": str(rid) in quarantined}
        for f_ in FIELDS:
            hv, ev = truth[f_], pred[f_]
            if hv is None or hv == "":
                rec[f_] = ("na", hv, ev)
                continue
            if ev is None:
                rec[f_] = (("quarantined" if rec["quarantined"] else "miss"), hv, ev)
                continue
            if f_ == "cpu_model":
                ok = norm_cpu(hv) == norm_cpu(ev)
            elif f_ == "ram_total_gb":
                ok = to_num(hv) == to_num(ev)
            elif f_ == "price_usd":
                hv, ev = to_num(hv), to_num(ev)
                ok = ev is not None and abs(ev - hv) <= max(1.0, 0.002 * hv)
            elif f_ == "chassis_model":
                a, b = norm_chassis(hv), norm_chassis(ev)
                ok = a == b or (len(a) >= 4 and (a in b or b in a))
            else:  # listing_status
                ok = str(ev) == str(hv)
            rec[f_] = (("hit" if ok else "miss"), hv, ev)
        rows.append(rec)

    # summary
    print("## Per-field hit rates\n")
    print("| field | applicable | hit | miss | hit rate |")
    print("|---|---|---|---|---|")
    for f_ in FIELDS:
        applicable = [r for r in rows if r[f_][0] in ("hit", "miss")]  # quarantined listings are excluded from rates
        hit = [r for r in applicable if r[f_][0] == "hit"]
        rate = f"{100 * len(hit) / len(applicable):.0f}%" if applicable else "—"
        print(f"| {f_} | {len(applicable)} | {len(hit)} | {len(applicable) - len(hit)} | {rate} |")

    qu = run.get("results", [])
    n_extracted = sum(1 for r in qu if r.get("outcome") == "extracted")
    n_quar = sum(1 for r in qu if r.get("outcome") in ("quarantined", "no_purchase_information"))
    print(f"\nOutcome split over {len(qu)} scored results: {n_extracted} extracted, {n_quar} quarantined/no-info.")

    print("\n## Per-listing score table\n")
    hdr = "| item_id | " + " | ".join(FIELDS) + " |"
    print(hdr)
    print("|" + "---|" * (len(FIELDS) + 1))
    for r in rows:
        cells = " | ".join(r[f_][0] for f_ in FIELDS)
        print(f"| {r['id']} | {cells} |")

    print("\n## Misses (with raw title)\n")
    printed = False
    for f_ in FIELDS:
        misses = [r for r in rows if r[f_][0] == "miss"]
        qm = sum(1 for r in rows if r[f_][0] == "quarantined")
        if qm:
            print(f"  ({f_}: +{qm} quarantined-listing cells, see below)")
        if not misses and not qm:
            continue
        if not misses:
            continue
        printed = True
        for r in misses:
            hv, ev = r[f_][1], r[f_][2]
            print(f"- **{f_}** `{r['id']}` human=`{hv}` engine=`{ev}` — {r['title']}")
    print("\n## Quarantined-listing cells (human read them; capture was a dead page)\n")
    for f_ in FIELDS:
        for r in rows:
            if r[f_][0] == "quarantined":
                print(f"- **{f_}** `{r['id']}` human=`{r[f_][1]}` engine=unparseable — {r['title']}")
    if not printed:
        print("(no misses on applicable fields)")

    print("\n## Not-applicable notes (engine answered where human read nothing)\n")
    for f_ in FIELDS:
        for r in rows:
            if r[f_][0] == "na" and r[f_][2] is not None:
                print(f"- **{f_}** `{r['id']}` engine=`{r[f_][2]}` (human left blank) — {r['title']}")
                break


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--humans", required=True)
    ap.add_argument("--ram-view-map", default=None,
                    help="JSON {item_id: ram_total_gb} from v_line_ram — preferred ram_total_gb source")
    args = ap.parse_args(argv)
    score(args.results, args.humans, args.ram_view_map)
    return 0


if __name__ == "__main__":
    sys.exit(main())
