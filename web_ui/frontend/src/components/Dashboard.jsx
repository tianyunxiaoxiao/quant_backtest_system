import React, { useEffect, useState } from 'react'
import {
  fetchArtifacts,
  fetchBenchmarkComparison,
  fetchBenchmarks,
  fetchChartData,
  fetchLatestPositions,
  fetchReportMarkdown,
  fetchRun,
  positionsExportUrl,
} from '../api'
import LineChart from './charts/LineChart'
import BarChart from './charts/BarChart'
import HeatmapChart from './charts/HeatmapChart'
import MetricCards from './MetricCards'

const fmtPct = (v) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return 'NA'
  return `${(v * 100).toFixed(2)}%`
}
const fmtNum = (v, digits = 2) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return 'NA'
  return v.toFixed(digits)
}
const fmtMoney = (v) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return 'NA'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
const fmtInt = (v) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return 'NA'
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}
const fmtRate = (v, digits = 4) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return 'NA'
  return `${(v * 100).toFixed(digits).replace(/\.?0+$/, '')}%`
}

const FREQUENCY_LABELS = {
  daily: '日度', weekly: '周度', monthly: '月度', target_weight_rows: '按权重文件日期',
}
const WEIGHTING_LABELS = {
  factor_strength: '因子强度',
  equal_weight: '等权',
  index_weight: '指数权重',
}
const FILL_PRICE_LABELS = { adj_vwap: 'VWAP', adj_open: '开盘价', adj_close: '收盘价' }
const FACTOR_SOURCE_LABELS = { demo: '内置公式', values: '导入数据', platform: '因子研究平台' }

const ParameterItem = ({ label, value, note }) => (
  <div className="parameter-item">
    <dt>{label}</dt>
    <dd>{value ?? 'NA'}</dd>
    {note && <small>{note}</small>}
  </div>
)

// 指标类型: pct = 百分比; num = 比率/数值; money = 货币金额; int = 计数。
// 2026-08-18 修复: 此前样本内/样本外列一律按百分比格式化, 导致
// 总成本显示成 1896365896.36%、Sharpe 显示成 39.75% 一类错误。
const METRIC_TYPES = {
  total_return: 'pct', annual_return: 'pct', annual_volatility: 'pct',
  sharpe: 'num', sortino: 'num', calmar: 'num',
  max_drawdown: 'pct',
  benchmark_annual_return: 'pct', benchmark_total_return: 'pct',
  excess_annual_return_geometric: 'pct', excess_total_return_geometric: 'pct',
  information_ratio: 'num',
  win_rate_daily: 'pct', win_rate_monthly: 'pct', win_rate_yearly: 'pct',
  turnover_annual_oneway: 'num',
  total_cost: 'money',
  cost_erosion_ratio: 'pct',
  avg_holdings: 'num',
  avg_top10_concentration: 'pct', avg_cash_ratio: 'pct',
}
const fmtMetric = (key, v) => {
  const type = METRIC_TYPES[key] || 'pct'
  if (type === 'pct') return fmtPct(v)
  if (type === 'money') return fmtMoney(v)
  if (type === 'int') return fmtInt(v)
  return fmtNum(v)
}

const TAB_CHARTS = {
  overview: [],
  returns: ['drawdown', 'monthly', 'annual', 'rolling'],
  alpha_beta: ['alpha_beta_contrib', 'alpha_beta_rolling'],
  style: ['style_timeseries', 'style_heatmap', 'style_summary'],
  costs: ['turnover_costs', 'coverage'],
  constraints: ['constraints', 'drawdown_table'],
  positions: [],
  report: [],
  artifacts: [],
}

const formatDuration = (seconds) => {
  const value = Math.max(0, Math.floor(Number(seconds) || 0))
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const secs = value % 60
  return [hours, minutes, secs].map(part => String(part).padStart(2, '0')).join(':')
}

export default function Dashboard({ run, activeTab, now, onCancel }) {
  const [data, setData] = useState({})
  const [loading, setLoading] = useState({})
  const [report, setReport] = useState('')
  const [artifacts, setArtifacts] = useState([])
  const [positions, setPositions] = useState(null)
  const [fullRun, setFullRun] = useState(null)
  const [benchmarks, setBenchmarks] = useState([])
  const [benchmarkId, setBenchmarkId] = useState('ALL_A_EQ')
  const [comparisonError, setComparisonError] = useState('')

  useEffect(() => {
    if (!run) return
    setFullRun(null)
    fetchRun(run.id).then(setFullRun)
    setBenchmarkId('ALL_A_EQ')
    setComparisonError('')
  }, [run?.id])

  useEffect(() => {
    fetchBenchmarks()
      .then(items => setBenchmarks(Array.isArray(items) ? items : []))
      .catch(() => setBenchmarks([]))
  }, [])

  useEffect(() => {
    if (!run || run.status !== 'completed') return
    const key = `${run.id}-comparison-${benchmarkId}`
    if (data[key]) return
    setLoading(l => ({ ...l, comparison: true }))
    setComparisonError('')
    fetchBenchmarkComparison(run.id, benchmarkId)
      .then(result => {
        setData(prev => ({ ...prev, [key]: result }))
        setLoading(l => ({ ...l, comparison: false }))
      })
      .catch(err => {
        setComparisonError(err.response?.data?.detail || err.message)
        setLoading(l => ({ ...l, comparison: false }))
      })
  }, [run?.id, run?.status, benchmarkId, data])

  useEffect(() => {
    if (!run || run.status !== 'completed') return
    const charts = TAB_CHARTS[activeTab] || []
    charts.forEach(chart => {
      if (data[`${run.id}-${chart}`]) return
      setLoading(l => ({ ...l, [chart]: true }))
      fetchChartData(run.id, chart)
        .then(d => {
          setData(prev => ({ ...prev, [`${run.id}-${chart}`]: d }))
          setLoading(l => ({ ...l, [chart]: false }))
        })
        .catch(() => setLoading(l => ({ ...l, [chart]: false })))
    })
  }, [run?.id, run?.status, activeTab])

  useEffect(() => {
    if (!run || activeTab !== 'report') return
    fetchReportMarkdown(run.id).then(setReport).catch(() => setReport('报告尚未生成'))
  }, [run?.id, activeTab])

  useEffect(() => {
    if (!run || activeTab !== 'artifacts') return
    fetchArtifacts(run.id).then(a => setArtifacts(a.filter(x => x.size > 0))).catch(() => setArtifacts([]))
  }, [run?.id, activeTab])

  useEffect(() => {
    if (!run || activeTab !== 'positions') return
    setPositions(null)
    fetchLatestPositions(run.id, 2).then(setPositions).catch(() => setPositions({ periods: [] }))
  }, [run?.id, activeTab])

  if (!run) {
    return (
      <div className="view active">
        <div className="empty-state">
          <strong>尚未选择回测结果</strong>
          <span>从左侧选择运行记录，或新建回测</span>
        </div>
      </div>
    )
  }

  const isRunning = run.status === 'running' || run.status === 'pending'
  const elapsedSeconds = run.status === 'running' && run.started_at
    ? (now - Date.parse(run.started_at)) / 1000
    : run.elapsed_seconds

  const performance = data[`${run.id}-performance`]
  const alphaBetaSummary = data[`${run.id}-alpha_beta`]
  const comparison = data[`${run.id}-comparison-${benchmarkId}`]
  const overviewPerformance = comparison?.performance || performance?.full_sample
  const overviewSummary = comparison?.summary || run.summary
  const overviewNav = comparison?.nav || data[`${run.id}-nav`]
  const runConfig = fullRun?.config

  const benchmarkToolbar = (
    <>
      <div className="benchmark-toolbar">
        <div>
          <span className="toolbar-label">对比基准</span>
          <strong>{loading.comparison ? '加载中' : comparison?.benchmark?.name || '加载中'}</strong>
        </div>
        <select
          value={benchmarkId}
          onChange={event => setBenchmarkId(event.target.value)}
          disabled={loading.comparison}
          aria-label="对比基准"
        >
          {benchmarks.map(item => (
            <option key={item.benchmark_id} value={item.benchmark_id}>
              {item.name} ({item.benchmark_id})
            </option>
          ))}
        </select>
      </div>
      {comparisonError && <div className="inline-error">基准切换失败：{comparisonError}</div>}
    </>
  )

  const comparisonChart = (name) => {
    if (comparison?.charts?.[name]) return comparison.charts[name]
    if (loading.comparison) return null
    return data[`${run.id}-${name}`]
  }

  const renderMarkdown = (md) => {
    // Very simple markdown-to-HTML conversion.
    const html = md
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/^### (.*$)/gim, '<h3>$1</h3>')
      .replace(/^## (.*$)/gim, '<h2>$1</h2>')
      .replace(/^# (.*$)/gim, '<h1>$1</h1>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br />')
    return { __html: html }
  }

  const tabContent = () => {
    switch (activeTab) {
      case 'overview':
        return (
          <>
            {benchmarkToolbar}
            <MetricCards summary={overviewSummary} />
            <div className="chart-grid">
              <LineChart data={overviewNav} title="组合 / 基准 / 超额收益率" yLabel="累计收益率" percentAxis />
            </div>
            {overviewPerformance && (
              <div className="content-section">
                <div className="section-heading"><h2>绩效指标详情</h2></div>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>指标</th>
                        <th>全样本</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        ['累计收益', 'total_return'],
                        ['年化收益', 'annual_return'],
                        ['年化波动', 'annual_volatility'],
                        ['Sharpe', 'sharpe'],
                        ['Sortino', 'sortino'],
                        ['最大回撤', 'max_drawdown'],
                        ['Calmar', 'calmar'],
                        ['基准年化收益', 'benchmark_annual_return'],
                        ['年化超额(几何)', 'excess_annual_return_geometric'],
                        ['信息比率', 'information_ratio'],
                        ['日胜率', 'win_rate_daily'],
                        ['月胜率', 'win_rate_monthly'],
                        ['年胜率', 'win_rate_yearly'],
                        ['年化换手(单边, 倍)', 'turnover_annual_oneway'],
                        ['总成本', 'total_cost'],
                        ['成本侵蚀比', 'cost_erosion_ratio'],
                        ['平均持股数', 'avg_holdings'],
                        ['前10集中度', 'avg_top10_concentration'],
                        ['现金比例', 'avg_cash_ratio'],
                      ].map(([label, key]) => (
                        <tr key={key}>
                          <td>{label}</td>
                          <td>{fmtMetric(key, overviewPerformance[key])}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            {runConfig && (
              <div className="content-section backtest-parameters">
                <div className="section-heading parameter-section-heading">
                  <h2>回测参数</h2>
                  <span>本次运行冻结配置</span>
                </div>

                <div className="parameter-group">
                  <h3>策略与组合</h3>
                  <dl className="parameter-grid">
                    <ParameterItem label="因子" value={run.factor_name || run.factor_id} note={run.factor_name ? run.factor_id : null} />
                    <ParameterItem label="组合输入" value={runConfig.portfolio_input_mode === 'direct_target_weights' ? '直接目标权重' : '因子分数'} />
                    <ParameterItem label="因子来源" value={FACTOR_SOURCE_LABELS[runConfig.factor_source] || runConfig.factor_source} />
                    <ParameterItem label="因子方向" value={runConfig.portfolio_input_mode === 'direct_target_weights' ? '不适用' : runConfig.factor_direction === -1 ? '-1 · 越小越好' : runConfig.factor_direction === 1 ? '+1 · 越大越好' : '按内置公式'} />
                    <ParameterItem label="回看窗口" value={runConfig.lookback == null ? '不适用' : `${runConfig.lookback} 日`} />
                    <ParameterItem label="选股股票池" value={runConfig.index_id} />
                    <ParameterItem label="回测区间" value={`${runConfig.start_date} ~ ${runConfig.end_date}`} />
                    <ParameterItem label="调仓频率" value={FREQUENCY_LABELS[runConfig.business_summary?.rebalance_frequency || runConfig.rebalance_frequency] || runConfig.business_summary?.rebalance_frequency || runConfig.rebalance_frequency} />
                    <ParameterItem label="信号滞后" value={`${runConfig.business_summary?.signal_lag_days ?? 1} 个交易日`} />
                    <ParameterItem label="初始资金" value={`¥ ${fmtMoney(runConfig.initial_capital)}`} />
                    <ParameterItem label="选股比例" value={runConfig.portfolio_input_mode === 'direct_target_weights' ? '不适用' : fmtPct(runConfig.selection_fraction)} />
                    <ParameterItem label="权重方法" value={runConfig.portfolio_input_mode === 'direct_target_weights' ? '上传权重原样使用' : WEIGHTING_LABELS[runConfig.weighting_method] || runConfig.weighting_method} />
                    <ParameterItem label="单票上限" value={runConfig.portfolio_input_mode === 'direct_target_weights' ? '由权重文件决定' : fmtPct(runConfig.max_single_weight)} />
                  </dl>
                </div>

                <div className="parameter-group execution-parameters">
                  <h3>交易与费用</h3>
                  <dl className="parameter-grid">
                    <ParameterItem label="成交价格" value={FILL_PRICE_LABELS[runConfig.fill_price_field] || runConfig.fill_price_field} />
                    <ParameterItem label="滑点" value={`${fmtNum(runConfig.slippage_bps)} bps`} note="嵌入成交价" />
                    <ParameterItem label="佣金率" value={fmtRate(runConfig.commission_rate)} note="买卖双边" />
                    <ParameterItem
                      label="最低佣金"
                      value={Number.isFinite(runConfig.min_commission) ? `¥ ${fmtMoney(runConfig.min_commission)}` : '未记录'}
                      note={Number.isFinite(runConfig.min_commission) ? '每笔成交' : '早期任务未冻结该字段'}
                    />
                    <ParameterItem
                      label="印花税"
                      value={runConfig.stamp_duty_rate == null ? '官方时变费率' : fmtRate(runConfig.stamp_duty_rate)}
                      note={runConfig.stamp_duty_rate == null ? '仅卖出；2023-08-28 起 0.05%' : '仅卖出'}
                    />
                    <ParameterItem
                      label="过户费"
                      value={runConfig.transfer_fee_rate == null ? '官方时变费率' : fmtRate(runConfig.transfer_fee_rate)}
                      note={runConfig.transfer_fee_rate == null ? '2022-04-29 起 0.001%' : null}
                    />
                  </dl>
                </div>
              </div>
            )}
          </>
        )
      case 'returns':
        return (
          <>
            {benchmarkToolbar}
            <div className="chart-grid">
              <LineChart data={comparisonChart('drawdown')} title="组合回撤与超额回撤" yLabel="回撤" percentAxis />
              <BarChart data={comparisonChart('monthly')} title="月度收益" />
              <BarChart data={comparisonChart('annual')} title="年度收益" />
              <LineChart data={comparisonChart('rolling')} title="滚动指标 (252日)" yLabel="" />
            </div>
          </>
        )
      case 'alpha_beta':
        return (
          <>
            {alphaBetaSummary && (
              <div className="metric-grid">
                <div className="metric-card"><span>Alpha (年化)</span><strong>{fmtPct(alphaBetaSummary.alpha_annual)}</strong></div>
                <div className="metric-card"><span>Beta</span><strong>{fmtNum(alphaBetaSummary.beta)}</strong></div>
                <div className="metric-card"><span>Alpha t-stat (NW)</span><strong>{fmtNum(alphaBetaSummary.alpha_tstat_nw)}</strong></div>
                <div className="metric-card"><span>R²</span><strong>{fmtNum(alphaBetaSummary.r_squared)}</strong></div>
              </div>
            )}
            <div className="chart-grid">
              <LineChart data={data[`${run.id}-alpha_beta_contrib`]} title="Alpha / Beta 累计贡献" yLabel="累计收益" percentAxis />
              <LineChart data={data[`${run.id}-alpha_beta_rolling`]} title="滚动 Alpha / Beta" />
            </div>
          </>
        )
      case 'style':
        const styleTs = data[`${run.id}-style_timeseries`]
        const hasValue = (arr) => arr && arr.some(v => v !== null && v !== undefined && Number.isFinite(v))
        const portfolioSeries = styleTs
          ? styleTs.styles
              .map(s => ({ name: s, values: styleTs.portfolio[s] }))
              .filter(s => hasValue(s.values))
          : []
        const activeSeries = styleTs
          ? styleTs.styles
              .map(s => ({ name: s, values: styleTs.active[s] }))
              .filter(s => hasValue(s.values))
          : []
        const styleSummary = data[`${run.id}-style_summary`]
        return (
          <>
            <div className="chart-grid">
              <LineChart data={{ dates: styleTs ? styleTs.dates : [], series: portfolioSeries }} title="组合风格暴露" />
              <LineChart data={{ dates: styleTs ? styleTs.dates : [], series: activeSeries }} title="主动风格暴露" />
              <HeatmapChart data={data[`${run.id}-style_heatmap`]} title="年度平均主动风格暴露" />
            </div>
            {styleSummary && (
              <div className="content-section">
                <div className="section-heading"><h2>风格暴露汇总</h2></div>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        {styleSummary.columns.map(c => <th key={c}>{c}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {styleSummary.rows.map((row, i) => (
                        <tr key={i}>{row.map((v, j) => <td key={j}>{typeof v === 'number' ? v.toFixed(2) : String(v)}</td>)}</tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )
      case 'costs':
        const cov = data[`${run.id}-coverage`]
        return (
          <div className="chart-grid">
            <LineChart data={data[`${run.id}-turnover_costs`]} title="换手率与交易成本" />
            <LineChart data={cov} title="指数成分 / 入选 / 持股 / 因子覆盖率" />
          </div>
        )
      case 'constraints':
        const dd = data[`${run.id}-drawdown_table`]
        const cons = data[`${run.id}-constraints`]
        return (
          <>
            {dd && (
              <div className="content-section">
                <div className="section-heading"><h2>回撤明细 (Top 10)</h2></div>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>{dd.columns.map(c => <th key={c}>{c}</th>)}</tr>
                    </thead>
                    <tbody>
                      {dd.rows.map((row, i) => (
                        <tr key={i}>
                          {row.map((v, j) => {
                            const col = dd.columns[j]
                            let text = String(v)
                            if (col === 'max_drawdown') text = fmtPct(v)
                            else if (col === 'duration_days' || col === 'to_trough_days' || col === 'recovery_days') text = Number.isFinite(v) ? String(v) : '-'
                            else if (col === 'is_recovered') text = v ? '是' : '否'
                            else if (col.endsWith('_date')) {
                              if (v === null || v === undefined || v === 'null' || v === 'NaT') text = '-'
                              else text = String(v).slice(0, 10)
                            }
                            return <td key={j}>{text}</td>
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            {cons && (
              <div className="content-section">
                <div className="section-heading"><h2>约束报告</h2></div>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>约束</th>
                        <th>启用</th>
                        <th>限制</th>
                        <th>检查数</th>
                        <th>违规数</th>
                        <th>最大观测</th>
                        <th>动作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cons.reports.map((r, i) => (
                        <tr key={i}>
                          <td>{r.constraint}</td>
                          <td>{r.enabled ? '是' : '否'}</td>
                          <td>{r.limit == null ? '-' : fmtNum(r.limit)}</td>
                          <td>{r.n_checked}</td>
                          <td>{r.n_violations}</td>
                          <td>{typeof r.max_observed === 'number' ? fmtNum(r.max_observed) : '-'}</td>
                          <td>{r.action}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )
      case 'positions':
        return (
          <div className="content-section">
            <div className="section-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2>历史持仓 · 最新两期调仓记录</h2>
              <a
                className="primary-button"
                style={{ textDecoration: 'none', padding: '8px 16px' }}
                href={positionsExportUrl(run.id)}
                download
              >
                ⬇ 下载全部历史 (CSV)
              </a>
            </div>
            {!positions ? (
              <div className="empty-state">加载中...</div>
            ) : positions.periods.length === 0 ? (
              <div className="empty-state">暂无成交记录</div>
            ) : (
              positions.periods.map(p => (
                <div key={p.date} style={{ marginBottom: 24 }}>
                  <div className="section-heading">
                    <h3>{p.date} 调仓</h3>
                    <span style={{ color: 'var(--muted)', fontSize: 12 }}>
                      买入 {p.n_buy} 笔 / {fmtMoney(p.buy_amount)} · 卖出 {p.n_sell} 笔 / {fmtMoney(p.sell_amount)} · 显式费用 {fmtMoney(p.explicit_cost)}
                    </span>
                  </div>
                  <div className="table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>标的</th>
                          <th>方向</th>
                          <th>成交股数</th>
                          <th>成交价</th>
                          <th>成交金额</th>
                          <th>佣金</th>
                          <th>印花税</th>
                          <th>过户费</th>
                          <th>费用合计</th>
                        </tr>
                      </thead>
                      <tbody>
                        {p.records.map((r, i) => (
                          <tr key={`${r.asset_id}-${i}`}>
                            <td>{r.asset_id}</td>
                            <td style={{ color: r.side === 'buy' ? '#ad3e2d' : '#176b4d' }}>{r.side === 'buy' ? '买入' : '卖出'}</td>
                            <td>{fmtInt(r.filled_quantity)}</td>
                            <td>{fmtNum(r.fill_price, 4)}</td>
                            <td>{fmtMoney(r.filled_amount)}</td>
                            <td>{fmtMoney(r.commission)}</td>
                            <td>{fmtMoney(r.stamp_duty)}</td>
                            <td>{fmtMoney(r.transfer_fee)}</td>
                            <td>{fmtMoney(r.explicit_cost)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))
            )}
          </div>
        )
      case 'report':
        return (
          <div className="content-section report-content">
            {report ? <div dangerouslySetInnerHTML={renderMarkdown(report)} /> : <div className="empty-state">报告加载中...</div>}
          </div>
        )
      case 'artifacts':
        return (
          <div className="content-section">
            <div className="section-heading"><h2>产物文件</h2></div>
            {artifacts.length === 0 ? (
              <div className="empty-state">暂无产物</div>
            ) : (
              <ul className="artifact-list">
                {artifacts.map(a => (
                  <li key={a.path}>
                    <a href={`/api/runs/${run.id}/artifacts/${a.path}`} target="_blank" rel="noreferrer">
                      <span>{a.name}</span>
                      <span>{(a.size / 1024).toFixed(1)} KB</span>
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )
      default:
        return null
    }
  }

  return (
    <div className="view active">
      <div className="result-heading">
        <div>
          <h1>{run.factor_name || run.factor_id} / {run.index_id}</h1>
          <span style={{ color: 'var(--muted)', fontSize: 12 }}>
            {run.factor_name ? `${run.factor_id} · ` : ''}
            {run.start_date} ~ {run.end_date} · {run.rebalance_frequency}
          </span>
        </div>
        <div className="result-state-block">
          <div className={`status-badge ${run.status}`}>{run.status}</div>
          {run.started_at && <span className="result-timing">耗时 {formatDuration(elapsedSeconds)}</span>}
        </div>
      </div>

      {isRunning && (
        <div className="progress-panel">
          <div className="progress-track"><i /></div>
          <div className="progress-detail">
            <strong>{run.status === 'running' ? '正在运行回测...' : '等待执行...'}</strong>
            <span>{run.status === 'running'
              ? `已运行 ${formatDuration(elapsedSeconds)}`
              : `已排队 ${formatDuration((now - Date.parse(run.created_at)) / 1000)}`}</span>
          </div>
          <button className="danger-button" type="button" onClick={() => onCancel(run.id)}>取消回测</button>
        </div>
      )}

      {run.status === 'cancelled' && (
        <div className="cancelled-panel">
          <strong>回测已取消</strong>
          <span>{run.started_at ? `运行耗时 ${formatDuration(run.elapsed_seconds)}` : '任务在排队阶段取消'}</span>
        </div>
      )}

      {run.status === 'failed' && run.error && (
        <div className="content-section" style={{ borderColor: '#dfb8b0', background: '#f8e9e6' }}>
          <strong>运行失败</strong>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>{run.error}</pre>
        </div>
      )}

      {run.status === 'completed' && tabContent()}
    </div>
  )
}
