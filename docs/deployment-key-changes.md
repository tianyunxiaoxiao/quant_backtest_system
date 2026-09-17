# 部署版关键修改点

本文记录 `de6dca3 feat: harden deployed backtest web platform` 之后固化的部署版能力。

## 1. 数据口径与仓库构建

- 新增 RQData 快照仓库构建流程：`scripts/ingest_rq_snapshot.py` 和 `src/qbt/data/ingest_rq_snapshot.py`。
- 回测仓库统一使用因子研究平台的不可变 `panel_shards` 快照，避免行情、ST、涨跌停、上市天数和研究股票池口径不一致。
- 默认研究股票池从“全 A 等权”调整为“流动性过滤后的非 ST A 股”。
- 新增 `data/dataset_release_20260825.json` 记录本次数据发布版本、时间范围、快照哈希和基准列表。

## 2. 因子输入与版本管理

- 支持导入因子值的多版本登记，新增 `factor_versions` 表。
- 因子文件按内容哈希保存，回测时冻结 `factor_version_id`、文件路径和内容哈希，保证历史 run 可复现。
- 支持两类输入：
  - `factor_scores`：普通因子分数，继续走选股和权重流程。
  - `target_weights`：目标权重文件，直接按上传权重调仓。
- 支持从因子研究平台读取用户可见因子，并通过内部 HMAC API 拉取不可变因子值文件。

## 3. Web 认证与权限

- 回测平台接入因子研究平台统一登录，不再维护第二套账号密码。
- 后端通过 HttpOnly Cookie 保存会话，并对写接口校验 CSRF token。
- run、导入因子、因子版本和产物均增加 owner 字段；普通研究员只能访问自己的记录，管理员可查看全部。
- 增加登录、登出、当前用户接口：`/api/auth/login`、`/api/auth/logout`、`/api/auth/me`。

## 4. 回测执行生命周期

- 回测任务从线程内执行调整为子进程执行，降低长任务影响 Web 服务的风险。
- 增加并发上限配置 `QBT_MAX_CONCURRENT_RUNS`。
- 增加 pending/running 任务取消能力。
- 服务重启时会把中断中的 pending/running 任务标记为 failed，避免页面长期显示假运行状态。

## 5. 报告与前端体验

- 新增报告期基准切换：可以把同一个回测结果与沪深300、中证500、中证1000等独立行情基准重新比较。
- 前端增加统一登录页、用户信息、任务取消按钮、运行耗时和队列等待时间。
- 配置页支持因子研究平台因子、导入因子版本和目标权重输入。
- Dashboard 只在任务完成后加载图表，避免 pending/running 状态触发无效请求。

## 6. 部署配置

- 新增 `web_ui/Dockerfile`，前端构建后随 FastAPI 后端一起服务。
- 新增 `.dockerignore`，排除本地数据仓库、运行产物、缓存和前端依赖目录。
- 新增 `web_ui/deploy.env.example`，列出生产环境需要注入的仓库路径、数据库路径、CORS、统一认证和 HMAC 配置。
- `web_ui/start.sh` 增加 Python 3.12+ 检查，并优先复用仓库根目录 `.venv`。

## 7. 真实股数与公司行动

- 执行引擎以交易所真实股数记账，持仓市值使用真实股数乘不复权价格，不再把后复权价格对应的
  比例误当成成交股数。
- 调仓日买入和非清仓卖出继续按 100 股整数手约束；送转产生的零股允许在整仓卖出时一次清掉。
- 交易所单笔申报上限按自动拆分子订单处理，不再限制单只股票当日聚合成交量；聚合成交仍受
  现金、换手率、涨跌停和最小申报数量约束。ADV 参与率上限默认关闭，
  显式配置 `max_adv_participation` 后才启用。
- 每日数据发布新增 `corporate_actions.parquet`，现金分红计入现金，送转比例调整持仓股数。
- 历史回测产物保持不可变；要得到修复后的持仓和成交股数，需要重新运行原回测。

## 8. 每日更新稳定性

- 日线、全量 5 分钟线、公司行动、指数基准和 Barra 数据统一使用最近已完成交易日。
- 候选版本先完成交易日、字段、哈希和 5 分钟完整性校验，再原子切换 `/data/research/current`。
- 发布成功后自动提交所有可执行、非隐藏因子的最新因子值任务；任务从其 `values_run_id` 对应
  成功 run 获取权威产物哈希，避免摘要并发刷新造成误判。
- recent-performance 只原子合并自身的诊断字段，不再整份覆盖因子摘要中的 `date_end`、
  `factor_values_hash` 和版本信息。

## 验证结果

提交前已执行：

```bash
env PYTHONPATH=src:web_ui/backend ./.venv/bin/python -m pytest tests web_ui/backend/tests
npm run build
git diff --cached --check
```

结果：

- Python 测试：`114 passed, 6 skipped`
- 前端生产构建：通过
- Git whitespace 检查：通过
