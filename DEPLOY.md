# Study 1 / Study 2 部署

统一部署和运行文档已整理到 [README.md](README.md)，依次包含：

1. Python 环境安装和 `.env` 配置。
2. SWE-Chat 访问授权、数据下载及所需 parquet 表。
3. 两项研究各自全量、200 并行的一键标注命令。
4. 全部主要指标、分母、缺失值与解释边界。
5. 成本敏感性与运行完整性说明。

入口分别为 `scripts/run_study1_pipeline.py` 和 `scripts/run_study2_pipeline.py`，共用
`scripts/run_study_pipeline.py`。同一输出目录不能被多个进程同时写入。
Study 1 pilot 修复后使用 README 中新的 `study1_100_seed42_v6` 输出目录；Study 2 继续使用其 `clean_v2` 目录。
Study 1 requirements v6 / behavior v4 需要重新标注；不要覆盖旧 pilot 或只补其 5 个失败 session。

流程审查见 [STUDY_REVIEW.md](STUDY_REVIEW.md)。凭据、原始数据和生成结果不应提交。
