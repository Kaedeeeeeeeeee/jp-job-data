# 人工抽检结论 — 2026-07-23

抽检对象：`artifacts/optimized-2026-07-23/jobs.json`

## 结论

- HelloWork、TokyoDev、JapanDev、Daijob、GaijinPot、JobsInJapan、Green、
  Forkwell 和 Wantedly 的数据质量满足当前使用要求。
- LinkedIn 公共访客接口返回的岗位经常缺少明确职责、薪资和可执行的职位描述，
  整体表达过于宽泛，不满足本项目的默认数据质量标准。

## 处理方式

- LinkedIn 适配器保留，确保历史实验可复现，也方便未来重新评估；
- LinkedIn 状态从 `active` 改为 `experimental`；
- `--sources=all` 默认只运行其余 9 个 active 来源；
- 只有显式使用 `--sources=linkedin` 或
  `--sources=all-including-experimental` 时才会采集 LinkedIn。

历史基线和优化实验仍保留原来的 10 平台口径，不回写或篡改已有实验结果。
