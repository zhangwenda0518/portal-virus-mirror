#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""portal_query.py — 离线查询 SRA 植物病毒监测快照 (API 失效后的等价查询入口)。

数据源: 本地 data/ (clone 仓库即用) 或 --remote 走 GitHub raw (带缓存)。

用法:
  python scripts/portal_query.py -q "yellow leaf curl"           # 病毒名子串 → 命中病毒列表
  python scripts/portal_query.py -q "yellow leaf curl" --runs    # 输出全部 Run 明细 (TSV)
  python scripts/portal_query.py --tax-id 3426741 --runs --side plant --min-spots 100
  python scripts/portal_query.py -q CMV --runs > cmv_runs.tsv
"""

import sys
if sys.platform == 'win32' and sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import os
import csv
import io
import gzip
import argparse
import urllib.request

DEFAULT_REPO_RAW = os.environ.get(
    "PORTAL_MIRROR_RAW",
    "https://raw.githubusercontent.com/zhangwenda0518/portal-virus-mirror/main/data")

_RUNS_HEADER = ["tax_id", "virus", "family", "genus", "acc", "side",
                "host", "host_family", "country", "year", "spots"]


def _fetch_remote(fname, cache_dir):
    url = f"{DEFAULT_REPO_RAW}/data/{fname}" if not DEFAULT_REPO_RAW.endswith("/data") \
        else f"{DEFAULT_REPO_RAW}/{fname}"
    print(f"  (fetch {fname} ...)", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": "portal-query"})
    with urllib.request.urlopen(req, timeout=600) as r:
        data = r.read()
    os.makedirs(cache_dir, exist_ok=True)
    tmp = os.path.join(cache_dir, fname + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, os.path.join(cache_dir, fname))
    return os.path.join(cache_dir, fname)


def _open(fname, data_dir, remote, cache_dir):
    local = os.path.join(data_dir, fname)
    if os.path.exists(local):
        return local
    if remote:
        return _fetch_remote(fname, cache_dir)
    raise FileNotFoundError(
        f"{fname} not in {data_dir}; clone the repo or pass --remote")


def _rows(fname, data_dir, remote, cache_dir):
    path = _open(fname, data_dir, remote, cache_dir)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t" if "runs_species" in fname else ","))


def main():
    ap = argparse.ArgumentParser(description="离线查询 SRA 植物病毒监测快照")
    ap.add_argument("-q", "--query", help="病毒名子串 (不区分大小写)")
    ap.add_argument("--tax-id", type=int, help="精确 tax_id")
    ap.add_argument("--runs", action="store_true", help="输出 Run 明细 (TSV); 缺省只列命中病毒")
    ap.add_argument("--side", default="both", choices=["plant", "insect", "both"])
    ap.add_argument("--min-spots", type=int, default=0)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--remote", action="store_true",
                    help="本地无数据时走 GitHub raw 在线拉取 (缓存于 scripts/.qcache)")
    a = ap.parse_args()
    if not a.query and not a.tax_id:
        ap.error("-q / --tax-id 至少一个")
    cd = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".qcache")
    hits = _rows("viruses_species.csv.gz", a.data_dir, a.remote, cd)
    q = (a.query or "").lower()
    sel = [r for r in hits
           if (a.tax_id and str(r["tax_id"]) == str(a.tax_id))
           or (q and q in str(r["name"]).lower())]
    if not sel:
        print(f"no virus hits (q={a.query!r}, tax_id={a.tax_id})")
        return 1
    print(f"{'tax_id':<10} {'virus':<48} {'family':<22} {'plant_runs':>10} {'insect_runs':>11}")
    for r in sorted(sel, key=lambda x: -int(x["plant_runs"] or 0)):
        print(f"{r['tax_id']:<10} {r['name']:<48} {r['family'] or '-':<22} "
              f"{r['plant_runs']:>10} {r['insect_runs'] or 0:>11}")

    if not a.runs:
        return 0
    total_runs = sum(int(r["plant_runs"] or 0) + int(r["insect_runs"] or 0) for r in sel)
    print(f"\n== runs for {len(sel)} virus(es), ~{total_runs} rows; "
          f"filters: side={a.side} min_spots={a.min_spots}")
    print("\t".join(_RUNS_HEADER))
    n_out = 0
    for r in _rows("runs_species.csv.gz", a.data_dir, a.remote, cd):
        if str(r["tax_id"]) not in {str(x["tax_id"]) for x in sel}:
            continue
        if a.side != "both" and r["side"] != a.side:
            continue
        try:
            if a.min_spots and float(r["spots"] or 0) < a.min_spots:
                continue
        except ValueError:
            pass
        print("\t".join(r[c] or "" for c in _RUNS_HEADER))
        n_out += 1
    print(str(n_out) + " run rows exported to stdout", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
