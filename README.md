# portal-virus-mirror

SRA 植物病毒监测平台 ([http://39.106.101.94/sra/](http://39.106.101.94/sra/)) 的**全量数据快照 + 离线查询工具** —— 平台不可用时, 数据与查询能力照常可用。

## 快照范围

平台把 NCBI SRA 全量元数据按植物界(taxid 33090 子树)/昆虫纲(taxid 50557 子树) Run 队列,
与 SRA STAT 病毒检出(k-mer spots)交叉构建。本快照覆盖平台全部公开数据:

| 内容 | 文件 | 规模 |
|---|---|---|
| 病毒列表(种/属/科三级 rank, 含两侧 run/spots/宿主种统计) | `data/viruses_{species,genus,family}.csv.gz` | 5,248 种 / 291 属 / 47 科 |
| 全量 Run 级检出明细 (病毒×Run 对, 一行一次检出) | `data/runs_species.csv.gz` | ~117 万行 |
| 板块汇总: summary / plant / insect / triple / graph / sankey | `data/*.json` | 全部 |
| 潜在样本 candidates (plant/insect × tier A-E) | `data/candidates_*.csv.gz` | 187,907 + 34,267 行 |

数据口径沿用平台 methods 页: STAT spots 是 k-mer 命中数, 反映序列丰度, 不等于感染确认;
植物病毒以 50 个植物病毒科为种子沿 NCBI 分类树取后代; ICTV 旧名经同义折叠解析。

## 用法

### 1. 离线查询 (clone 即查)

```bash
git clone https://github.com/zhangwenda0518/portal-virus-mirror.git
cd portal-virus-mirror
python scripts/portal_query.py -q "yellow leaf curl" --runs > tylcv_runs.tsv
python scripts/portal_query.py -q CMV --side plant --min-spots 100
```

用法示例第二行输出格式: 病毒命中列表 + 全部 Run 明细 TSV (tax_id, virus, family, genus,
acc, side, host, host_family, portal country/year/spots)。

### 2. 免 clone 在线查询 (--remote)

```bash
```

### 2. 免 clone 在线查询 (--remote)

```bash
python scripts/portal_query.py -q "yellow leaf curl" --runs --remote
```

数据从 raw.githubusercontent.com 拉取并缓存到 `scripts/.qcache/`（重复查询不重下）。

### 3. 快照刷新（平台可用时增量续命）

```bash
python scripts/portal_mirror.build.py --all --workers 4   # 全量 ~10-20 分钟
python scripts/portal_mirror.build.py --lists             # 只刷列表+板块 ~1 分钟
```

GitHub Actions 每周一 02:00 UTC 自动重抓全量并提交（平台挂掉时 workflow 失败不影响已有快照）。

## GitHub Actions 自动刷新

`.github/workflows/refresh.yml` 每周自动: 抓取 → 重新生成快照 → 自动 commit。
快照由 [portal_mirror.build.py](scripts/portal_mirror.build.py) 构建, 单文件远小于 GitHub 100MB 限制。

## 来源与口径声明

- 数据来源: NCBI SRA 公共数据, 经 39.106.101.94 平台聚合 (平台构建时间见 `data/summary.json` 的 `meta.build_time`)
- 本仓库是公共数据快照的再分发, 遵循 NCBI 数据使用政策
- spots 是 k-mer 命中数, 反映序列丰度, **不等于感染确认**; 低 spots 可能来自环境背景/污染/参考库交叉映射
- 引用平台时请注明: NCBI SRA STAT + SRA metadata 聚合平台 (build_time 见 MANIFEST)

## License

代码 MIT; 数据遵循 NCBI 公共域数据政策。
