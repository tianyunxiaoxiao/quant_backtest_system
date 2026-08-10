# 精简交付清单

## 包含内容

- `src/qbt/`: 完整回测、数据、分析、报告和 CLI 实现。
- `warehouse/`: 2015-2026 年运行所需的 Parquet 行情、交易日历及指数缓存。
- `data/index_membership_source/`: 三个受支持指数所需的 15 个 PIT 月度快照。
- `scripts/ingest_data.py`: 可选的数据重新摄取入口。
- `pyproject.toml`、`requirements.txt`: 安装和依赖定义。
- `artifacts/`: 新回测的输出位置，交付时为空。

## 有意排除

- `.git/`、`.venv/` 及编辑器、Python、pytest、mypy、Ruff 缓存。
- 单元、集成和回归测试源码；测试已在制作此副本时从外部验证套件执行。
- 旧回测输出、隔离的无效输出、覆盖率数据库和验证过程文件。
- 3 GB 原始逐股 CSV 备份；运行使用已摄取并校验的 Parquet 仓库。
- 未被支持指数配置使用的中证 2000 代理文件、Office 锁文件和 `.DS_Store`。

## 自包含约束

CLI 默认从本目录的 `warehouse/` 和 `data/index_membership_source/` 读取数据，
不依赖原项目、父目录或开发虚拟环境。首次运行时会在 `artifacts/` 下生成结果。

## 交付验证（2026-08-08）

- 原完整测试套件的 100 项测试全部通过，包括真实数据集成与报告重载。
- Ruff 检查通过；mypy 在实际 Python 3.14 环境下检查 36 个源码文件无问题。
- 源码编译、警告严格模式 CLI 启动及临时目录隔离安装均通过。
- 省略 `--index` 的全 A 等权实际 CLI 回测通过：7 个交易日，账户恒等式显示残差
  `0.000000 bps`。
- 显式 `--index 000905.SH` 的中证 500 实际 CLI 回测通过：7 个交易日，账户恒等式
  显示残差 `0.000000 bps`。
- 12 个年度行情分区和整个 Parquet 仓库与已验收原项目逐文件一致。
- 精简目录包含 36 个 Python 源文件、15 个必要指数 Excel 快照；交付前
  `artifacts/` 已恢复为空。
- 最终占用 974,624 KiB（约 952 MiB），原项目约 2.8 GiB。

除清单自身外的最终文件级 SHA-256 清单见 `SHA256SUMS`。
