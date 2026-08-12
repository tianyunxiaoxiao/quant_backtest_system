# 量化回测可视化 (Quant Backtest Web)

基于现有 A 股指数内多头因子回测框架 `qbt` 的独立 Web 可视化版本。

**本目录完全新建，未修改原系统 `quant_backtest_system_clean` 的任何文件。**

## 目录结构

```text
quant_backtest_web/
├── backend/                 # FastAPI 后端
│   ├── qbt_web/
│   │   ├── engine.py        # 只读引用原 qbt，执行回测
│   │   ├── routers/         # API 路由
│   │   └── services/        # 运行器 + 图表数据转换
│   └── requirements.txt
├── frontend/                # React + Vite + Plotly 前端
│   ├── src/
│   └── dist/                # 构建产物（可重新生成）
├── data/runs/               # 每次回测产物目录（运行时生成）
├── qbt_web.db               # SQLite 运行记录（运行时生成）
├── start.sh                 # 一键启动脚本（创建环境 + 构建 + 启动）
├── start_backend.sh         # 仅启动后端（需已完成构建）
├── .env.example             # 环境变量示例
└── README.md
```

## 前置条件

- Python 3.11+
- Node.js 18+
- 本目录需要和原系统目录放在同一父目录下：

  ```text
  TC5days20260806/
    ├── quant_backtest_system_clean/
    └── quant_backtest_web/
  ```

  如果原系统位置不同，可复制 `.env.example` 为 `.env` 并设置 `QBT_PROJECT_ROOT`。

## 一键启动（推荐）

```bash
cd quant_backtest_web
./start.sh
```

脚本会自动完成：

1. 创建 Python 虚拟环境 `.venv`。
2. 安装后端依赖。
3. 安装前端依赖并构建 `frontend/dist/`。
4. 启动 FastAPI 服务。

然后打开浏览器访问 `http://localhost:8000`。

## 分步部署（想手动控制时）

```bash
cd quant_backtest_web

# 后端
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# 前端
cd frontend
npm install
npm run build
cd ..

# 启动
cd backend
PYTHONPATH=. uvicorn qbt_web.main:app --host 0.0.0.0 --port 8000
```

## 日常使用

- 已有构建产物时，只想重新启动后端：

  ```bash
  ./start_backend.sh
  ```

- 修改前端代码后重新构建：

  ```bash
  cd frontend && npm run build && cd ..
  ./start_backend.sh
  ```

## 打包给别人

把 `quant_backtest_web/` 整个文件夹压缩即可。接收方解压后保证它和 `quant_backtest_system_clean/` 在同一父目录，然后执行：

```bash
cd quant_backtest_web
./start.sh
```

**压缩前建议排除以下内容以减小体积**（见 `.gitignore`）：

- `.venv/`
- `frontend/node_modules/`
- `frontend/dist/`（可选，启动脚本会自动构建）
- `data/runs/`
- `qbt_web.db`
- `__pycache__/` / `*.pyc`
- `.DS_Store`

## 使用说明

1. 打开首页后，点击「新建回测」。
2. 选择因子、基准指数、回测区间、调仓频率、初始资金、选股比例、权重方法等。
3. 点击「运行回测」，左侧运行记录会显示状态，完成后自动展示结果。
4. 顶部标签页切换：
   - **概览**：核心指标卡、净值曲线、绩效指标详情表。
   - **收益分析**：回撤、月度/年度收益、滚动收益/波动/Sharpe/IR。
   - **Alpha / Beta**：Alpha/Beta 累计贡献、滚动 Alpha/Beta/R²/t-stat。
   - **风格暴露**：组合/主动风格暴露时间序列、年度主动暴露热力图、风格汇总表。
   - **执行成本**：换手率与成本、ADV 参与率、成分股/入选/持股/覆盖率。
   - **持仓约束**：回撤明细 Top 10、约束报告。
   - **报告**：渲染的 Markdown 回测报告。
   - **产物**：所有 Parquet / JSON / PNG / Markdown 产物下载。

## 环境变量

复制 `.env.example` 为 `.env`，按需修改：

| 变量                 | 说明                                      |
| -------------------- | ----------------------------------------- |
| `QBT_PROJECT_ROOT`   | 原 `quant_backtest_system_clean` 目录路径 |
| `QBT_WAREHOUSE`      | 数据仓库目录                              |
| `QBT_INDEX_DIR`      | 指数成分来源目录                          |
| `OUTPUT_ROOT`        | 产物输出目录                              |
| `DATABASE_PATH`      | SQLite 数据库路径                         |
| `CORS_ORIGINS`       | 跨域来源，如 `["*"]`                      |

## 部署到 Render（示例）

- **Build Command**：

  ```bash
  pip install -r backend/requirements.txt && cd frontend && npm install && npm run build
  ```

- **Start Command**：

  ```bash
  cd backend && PYTHONPATH=. uvicorn qbt_web.main:app --host 0.0.0.0 --port $PORT --workers 1
  ```

- 长时间回测已使用后台任务 + 前端轮询，避免 Render 100 秒超时。
- 建议单 worker，避免 matplotlib 并发冲突。

## 验证记录

- API：`/api/factors`、`/api/indexes`、提交回测、轮询状态、全部 16 个 `chart-data` 端点均返回 200。
- 浏览器：使用 Playwright 遍历所有标签页，无 JavaScript 错误。
- 已测试场景：月度全区间（2018–2026）、日度短区间（2023 全年）。

## 与原系统的关系

- 原系统：`/Users/a1/Desktop/添橙/TC5days20260806/quant_backtest_system_clean`
- 本系统通过 `sys.path` 在运行时导入 `qbt`，产物写入本目录的 `data/runs/`，不会修改原系统。
