# jpjobs 0.4 架构与数据流程

本文描述当前优化版本从搜索参数、平台抓取、日期自动分页，到规范化、详情补全、
过滤、去重和输出的运行逻辑。

## 主流程

```mermaid
flowchart TD
    A["用户调用<br/>CLI 或 Python API"] --> B["解析查询与输出参数"]
    B --> C["选择 10 个 active 来源<br/>或用户指定来源"]
    C --> D["最多 2 个来源并发运行"]

    D --> E1["浏览器适配器<br/>HelloWork"]
    D --> E2["HTTP / 公开接口适配器<br/>其余 9 个 active 来源"]

    E1 --> F["平台搜索、排序和分页"]
    E2 --> F

    F --> G{"分页模式"}
    G -->|"--pages=N"| G1["最多请求 N 页"]
    G -->|"--pages=auto"| G2["日期驱动自动分页"]

    G2 --> G3{"停止条件"}
    G3 --> G31["站点没有下一页"]
    G3 --> G32["可靠时间顺序越过日期边界"]
    G3 --> G33["达到 max_pages 安全上限"]
    G3 --> G34["平台重复返回同一页"]

    G1 --> H["统一 Job 对象"]
    G31 --> H
    G32 --> H
    G33 --> H
    G34 --> H

    H --> I["normalize.py<br/>日期、公司、地点、雇佣类型、语言"]
    I --> J{"--fetch-details？"}
    J -- "是" --> J1["读取 schema.org JobPosting<br/>补全描述、日期、薪资和地点"]
    J -- "否" --> K
    J1 --> K["全局严格过滤"]

    K --> K1["日期窗口"]
    K --> K2["关键词"]
    K --> K3["都道府县"]
    K --> K4["雇佣类型与语言"]

    K1 --> L["同平台 ID 去重<br/>跨平台公司 + 标题去重"]
    K2 --> L
    K3 --> L
    K4 --> L

    L --> M["ScanResult"]
    M --> M1["岗位数据"]
    M --> M2["过滤与去重统计"]
    M --> M3["平台状态"]
    M --> M4["分页页数、停止原因、覆盖状态"]

    M --> N1["JSON / CSV / Markdown / Table / LLM"]
    M --> N2["SQLite 增量存储"]
    M --> N3["浏览器抽检页面"]
```

## 日期自动分页

```mermaid
stateDiagram-v2
    [*] --> FetchPage
    FetchPage --> SourceEnd: 没有下一页
    FetchPage --> DateBoundary: 整页或最旧记录已早于窗口
    FetchPage --> SafetyCap: 达到 max_pages
    FetchPage --> RepeatedPage: 没有新增岗位
    FetchPage --> RateLimit: 继续前等待
    RateLimit --> FetchPage

    SourceEnd --> Complete
    DateBoundary --> Complete
    SafetyCap --> PossiblyIncomplete
    RepeatedPage --> PossiblyIncomplete
```

不同平台不能使用同一种日期停止判断：

- 有服务端日期过滤的平台继续翻到接口结束；
- 有可靠 newest-first 顺序的平台在越过日期边界后停止；
- 默认相关性排序的平台遍历来源库存或到安全上限；
- 只有详情页日期的平台会探测每页最旧岗位的详情日期；
- 单页返回全部库存的平台不进行伪分页。

详见 [数据抽检与日期自动分页](./audit-and-auto-pagination.md)。

## 关键模块

| 模块 | 责任 |
|---|---|
| `cli.py` | 参数解析，包括 `--pages=auto` 和 `--max-pages` |
| `aggregate.py` | 来源并发、规范化、详情补全、全局过滤、去重和统计 |
| `pagination.py` | 共享页数预算、日期边界和覆盖状态判定 |
| `sources/*.py` | 平台查询参数、排序、分页、列表解析与停止信号 |
| `enrich.py` | 解析 schema.org `JobPosting` 详情 |
| `normalize.py` | 统一文本、日期、公司、地点、雇佣与语言字段 |
| `filtering.py` | 跨平台一致的日期和查询条件后置过滤 |
| `storage.py` | SQLite run、job 和 sighting 增量记录 |
| `output.py` | JSON、CSV、Markdown、终端表格和 LLM 输出 |
| `experiments/build_audit_report.py` | 生成自包含人工抽检页面 |

## 覆盖状态的含义

每个 `SourceStats` 会返回：

```json
{
  "pages_fetched": 8,
  "pagination_stop_reasons": ["date_boundary"],
  "coverage_complete": true
}
```

- `true`：站点已结束、单页库存已完整返回，或可靠日期顺序已经越过窗口；
- `false`：安全上限或重复页使扫描提前停止，窗口内可能还有更多岗位；
- `null`：旧式或第三方来源没有报告分页证据。

这一区分避免把“成功请求了几页”误报成“已经抓全平台”。
