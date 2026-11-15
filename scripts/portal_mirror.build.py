#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SRA 植物病毒监测平台 (http://39.106.101.94/sra/) 全量数据快照构建器。

抓取:
  1. 病毒列表 3 个 rank (species/genus/family) — /sra/api/virus 翻页
  2. 板块汇总 API (summary/plant/insect/triple/graph/sankey/candidates 分 tier)
  3. 全部病毒详情页 → 解析内嵌 DATA JSON → 流式写入 runs_species.csv.gz
     (字段: tax_id<TAB>name<TAB>family<TAB>genus<TAB>acc<TAB>side<TAB>host<TAB>
      host_family<TAB>country<TAB>year<TAB>spots; 一行=一个 Run 在该病毒下的检出)

用法:
  python portal_mirror.build.py --all          # 全量 (列表+板块+详情页)
  python portal_mirror.build.py --lists        # 只刷列表+板块 (快, ~1 分钟)
  python portal_mirror.build.py --runs-only    # 只刷详情页 (慢, ~10-20 分钟)
  python portal_mirror.build.py --all --data-dir ../data --workers 4
"""

import sys
if sys.platform == 'win32' and sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import os
import csv
import re
import json
import gzip
import time
import argparse
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.environ.get("MMPV_PORTAL_URL", "http://39.106.101.94")
UA = {"User-Agent": "Mozilla/5.0 (portal-mirror-builder)"}

DATA_ANCHOR = re.compile(
    r"var\s+DATA\s*=\s*(\[.*?\])\s*;\s*\n\s*window\.PVDB_DETAIL_DATA", re.S)
TITLE = re.compile(r"<title>([^<]+?)\s*·")

RUNS_HEADER = ["tax_id", "virus", "family", "genus", "acc", "side",
               "host", "host_family", "country", "year", "spots"]

RATE_LIMIT_S = 0.15          # 同步请求间隔 (礼貌限速)
_LOCK = threading.Lock()
_LAST_TS = [0.0]


def _pace():
    with _LOCK:
        wait = RATE_LIMIT_S - (time.time() - _LAST_TS[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_TS[0] = time.time()


def _get_bytes(url, timeout=120, retries=3):
    last = None
    for i in range(retries):
        _pace()
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET {url} failed after {retries} tries: {last}")


def _json(url, **kw):
    return json.loads(_get_bytes(url, **kw).decode("utf-8", "replace"))


def fetch_list(rank, data_dir):
    """抓 rank 级病毒列表 (翻页), 存 viruses_{rank}.json + csv.gz。"""
    rows, o = [], 0
    total = None
    while True:
        d = _json(f"{BASE}/sra/api/virus?rank={rank}&n=500&o={o}")
        total = d.get("total", total)
        rows.extend(d["rows"])
        if len(rows) >= (total or 0) or not d["rows"]:
            break
        o += 500
    out_json = os.path.join(data_dir, f"viruses_{rank}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    # csv.gz 精简版
    cols = ["tax_id", "name", "rank", "family", "genus",
            "plant_runs", "plant_spots", "plant_host_species",
            "insect_runs", "insect_spots", "insect_host_species"]
    with gzip.open(os.path.join(data_dir, f"viruses_{rank}.csv.gz"), "wt",
                   encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  [list:{rank}] {len(rows)} rows -> viruses_{rank}.csv.gz")
    return rows


def fetch_boards(data_dir):
    """板块汇总 API → json + csv.gz (candidates 按 side 分 tier 全量翻页)。"""
    # 简单端点: 直接整包 JSON
    simple = {
        "summary": "/sra/api/summary",
        "board_plant": "/sra/api/plant?level=species&n=100000",
        "triple_plant": "/sra/api/triple?side=plant&n=100000",
        "triple_insect": "/sra/api/triple?side=insect&n=100000",
        "graph_plant": "/sra/api/graph?side=plant",
        "graph_insect": "/sra/api/graph?side=insect",
        "sankey_plant": "/sra/api/sankey?side=plant",
        "sankey_insect": "/sra/api/sankey?side=insect",
    }
    for name, path in simple.items():
        try:
            d = _json(f"{BASE}{path}", timeout=300)
            with open(os.path.join(data_dir, f"{name}.json"), "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            print(f"  [board:{name}] {len(json.dumps(d)) / 1e6:.1f}MB")
        except Exception as e:
            print(f"  [board:{name}] FAILED: {e}")

    # candidates: side × tier 全量翻页 (每 side total≈18-19 万)
    for side in ("plant", "insect"):
        tiers = {}
        try:
            tiers = _json(f"{BASE}/sra/api/summary")["candidate_tiers"][side]
        except Exception:
            pass
        tier_names = [t["tier"] for t in tiers] if tiers else ["A", "B", "C", "D", "E"]
        for tier in tier_names:
            rows, o = [], 0
            while True:
                d = _json(f"{BASE}/sra/api/candidates?side={side}&tier={tier}&n=500&o={o}",
                          timeout=300)
                rows.extend(d["rows"])
                total = d.get("total", len(rows))
                if len(rows) >= total or not d["rows"]:
                    break
                o += 500
            if rows:
                cols = list(rows[0].keys())
                with gzip.open(os.path.join(data_dir, f"candidates_{side}_{tier}.csv.gz"),
                               "wt", encoding="utf-8", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)
                print(f"  [candidates:{side}:{tier}] {len(rows)} rows")


def fetch_runs(data_dir, workers=4):
    """全量抓病毒详情页 → 解析内嵌 DATA → 流式追加 runs_species.csv.gz。"""
    with open(os.path.join(data_dir, "viruses_species.json"), encoding="utf-8") as f:
        viruses = json.load(f)
    # 大病毒先跑 (长尾失败重试从容)
    viruses.sort(key=lambda r: -(r.get("plant_runs") or 0) - (r.get("insect_runs") or 0))

    runs_path = os.path.join(data_dir, "runs_species.csv.gz")
    n_done, n_fail, lock = 0, 0, threading.Lock()

    def work(tax_id):
        url = f"{BASE}/sra/virus/{tax_id}"
        for attempt in range(3):
            try:
                return _get_bytes(url, timeout=300)
            except Exception:
                time.sleep(2 * (attempt + 1))
        return None

    def handle(tax_id, name, family, genus, html):
        m = DATA_ANCHOR.search(html)
        if not m:
            return 0, "no-anchor"
        runs = json.loads(m.group(1))
        out = []
        for r in runs:
            out.append("\t".join([
                str(tax_id), name, family or "", genus or "",
                r.get("acc") or "", r.get("side") or "",
                r.get("host") or "", r.get("host_family") or "",
                r.get("country") or "",
                str(r["theyear"]) if r.get("theyear") is not None else "",
                str(r.get("spots") if r.get("spots") is not None else ""),
            ]))
        return len(out), "\n".join(out)

    def task(h):
        tax_id = h["tax_id"]
        html_b = work(tax_id)
        if html_b is None:
            return ("FAIL", tax_id, 0)
        html = html_b.decode("utf-8", "replace")
        n, payload = handle(tax_id, h.get("name") or "", h.get("family"),
                            h.get("genus"), html)
        if n == 0:
            return ("NO-DATA", tax_id, 0)
        return ("OK", tax_id, payload)

    print(f"  [runs] {len(viruses)} viruses, {workers} workers, START")
    t0 = time.time()
    with gzip.open(runs_path, "wt", encoding="utf-8", newline="") as gz:
        w = csv.writer(gz, delimiter="\t")
        w.writerow(RUNS_HEADER)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(task, h): h for h in viruses}
            for fut in as_completed(futs):
                status, tax_id, payload = fut.result()
                with lock:
                    if status == "OK":
                        gz.write(payload + "\n")
                        n_done += 1
                    else:
                        n_fail += 1
                        print(f"    {status}: tax={tax_id}")
                    if (n_done + n_fail) % 200 == 0:
                        print(f"    progress {(n_done + n_fail)}/{len(viruses)} "
                              f"({time.time() - t0:.0f}s)")
    print(f"  [runs] done: {n_done} ok, {n_fail} failed, {time.time() - t0:.0f}s")
    return n_fail


def build_manifest(data_dir):
    """生成 MANIFEST.json: 文件清单 + 行数 + 抓取时间。"""
    import datetime
    import subprocess
    files = {}
    for fn in sorted(os.listdir(data_dir)):
        p = os.path.join(data_dir, fn)
        if os.path.isfile(p):
            files[fn] = {"bytes": os.path.getsize(p)}
    manifest = {
        "source": f"{BASE}/sra/",
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "row_counts": {
            "viruses_species": sum(1 for _ in gzip.open(
                os.path.join(data_dir, "runs_species.csv.gz"), "rt")) - 1
            if os.path.exists(os.path.join(data_dir, "runs_species.csv.gz")) else 0,
        },
        "files": files,
    }
    with open(os.path.join(data_dir, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"  [manifest] {len(files)} files")
    return manifest


def main():
    ap = argparse.ArgumentParser(description="SRA 植物病毒监测平台数据快照构建器")
    ap.add_argument("--all", action="store_true", help="全量: 列表+板块+详情页")
    ap.add_argument("--lists", action="store_true", help="只刷病毒列表 + 板块汇总")
    ap.add_argument("--runs-only", action="store_true", help="只刷病毒详情页 Run 明细")
    ap.add_argument("--data-dir", default=None, help="数据目录 (默认 ../data)")
    ap.add_argument("--workers", type=int, default=4, help="详情页并发数 (默认 4)")
    a = ap.parse_args()
    if not (a.all or a.lists or a.runs_only):
        ap.error("--all / --lists / --runs-only 至少一个")

    here = os.path.dirname(os.path.abspath(__file__))
    data_dir = a.data_dir or os.path.normpath(os.path.join(here, "..", "data"))
    os.makedirs(data_dir, exist_ok=True)

    if a.lists or a.all:
        print("== 1) 病毒列表 (species/genus/family)")
        for rank in ("species", "genus", "family"):
            fetch_list(rank, data_dir)
        print("== 2) 板块汇总 (summary/plant/insect/triple/graph/sankey/candidates)")
        fetch_boards(data_dir)

    if a.runs_only or a.all:
        print("== 3) 病毒详情页 Run 明细 (全量)")
        fails = fetch_runs(data_dir, workers=a.workers)
        if fails:
            print(f"  ⚠️ {fails} 个病毒拉取失败, 重跑 --runs-only 可增量补")

    print("== 4) MANIFEST")
    build_manifest(data_dir)
    print("done ->", data_dir)


if __name__ == "__main__":
    main()
