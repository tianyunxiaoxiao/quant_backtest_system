import React, { useEffect, useState } from 'react'
import {
  fetchArtifacts,
  fetchChartData,
  fetchReportMarkdown,
  fetchRun,
} from '../api'
import LineChart from './charts/LineChart'
import BarChart from './charts/BarChart'
import HeatmapChart from './charts/HeatmapChart'
import MetricCards from './MetricCards'

const fmtPct = (v) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return 'NA'
  return `${(v * 100).toFixed(2)}%`
}
const fmtNum = (v) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return 'NA'
  return v.toFixed(3)
}

const TAB_CHARTS = {
  overview: ['nav', 'performance', 'alpha_beta'],
  returns: ['drawdown', 'monthly', 'annual', 'rolling'],
  alpha_beta: ['alpha_beta_contrib', 'alpha_beta_rolling'],
  style: ['style_timeseries', 'style_heatmap', 'style_summary'],
  costs: ['turnover_costs', 'coverage'],
  constraints: ['constraints', 'drawdown_table'],
  report: [],
  artifacts: [],
}

export default function Dashboard({ run, activeTab }) {
  const [data, setData] = useState({})
  const [loading, setLoading] = useState({})
  const [report, setReport] = useState('')
  const [artifacts, setArtifacts] = useState([])
  const [fullRun, setFullRun] = useState(null)

  useEffect(() => {
    if (!run) return
    fetchRun(run.id).then(setFullRun)
  }, [run?.id])

  useEffect(() => {
    if (!run) return
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
  }, [run?.id, activeTab])

  useEffect(() => {
    if (!run || activeTab !== 'report') return
    fetchReportMarkdown(run.id).then(setReport).catch(() => setReport('报告尚未生成'))
  }, [run?.id, activeTab])

  useEffect(() => {
    if (!run || activeTab !== 'artifacts') return
    fetchArtifacts(run.id).then(a => setArtifacts(a.filter(x => x.size > 0))).catch(() => setArtifacts([]))
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

  const performance = data[`${run.id}-performance`]
  const alphaBetaSummary = data[`${run.id}-alpha_beta`]

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
            <MetricCards summary={run.summary} />
            <div className="chart-grid">
              <LineChart data={data[`${run.id}-nav`]} title="组合 / 基准 / 超额净值" yLabel="净值" percentAxis />
            </div>
            {performance && performance.full_sample && (
              <div className="content-section">
                <div className="section-heading"><h2>绩效指标详情</h2></div>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>指标</th>
                        <th>全样本</th>
                        {performance.in_sample && <th>样本内</th>}
                        {performance.out_of_sample && <th>样本外</th>}
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
                        ['年化换手(单边)', 'turnover_annual_oneway'],
                        ['总成本', 'total_cost'],
                        ['成本侵蚀比', 'cost_erosion_ratio'],
                        ['平均持股数', 'avg_holdings'],
                        ['前10集中度', 'avg_top10_concentration'],
                        ['现金比例', 'avg_cash_ratio'],
                      ].map(([label, key]) => (
                        <tr key={key}>
                          <td>{label}</td>
                          <td>{key === 'avg_holdings' || key === 'total_cost' ? fmtNum(performance.full_sample[key]) : fmtPct(performance.full_sample[key])}</td>
                          {performance.in_sample && <td>{fmtPct(performance.in_sample[key])}</td>}
                          {performance.out_of_sample && <td>{fmtPct(performance.out_of_sample[key])}</td>}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )
      case 'returns':
        return (
          <div className="chart-grid">
            <LineChart data={data[`${run.id}-drawdown`]} title="组合回撤与超额回撤" yLabel="回撤" percentAxis />
            <BarChart data={data[`${run.id}-monthly`]} title="月度收益" />
            <BarChart data={data[`${run.id}-annual`]} title="年度收益" />
            <LineChart data={data[`${run.id}-rolling`]} title="滚动指标 (252日)" yLabel="" />
          </div>
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
                        <tr key={i}>{row.map((v, j) => <td key={j}>{typeof v === 'number' ? v.toFixed(3) : String(v)}</td>)}</tr>
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
          <h1>{run.factor_id} / {run.index_id}</h1>
          <span style={{ color: 'var(--muted)', fontSize: 12 }}>
            {run.start_date} ~ {run.end_date} · {run.rebalance_frequency}
          </span>
        </div>
        <div className="result-state-block">
          <div className={`status-badge ${run.status}`}>{run.status}</div>
          {run.completed_at && <span style={{ color: 'var(--muted)', fontSize: 11 }}>{run.completed_at}</span>}
        </div>
      </div>

      {isRunning && (
        <div className="progress-panel">
          <div className="progress-track"><i /></div>
          <div className="progress-detail">
            <strong>{run.status === 'running' ? '正在运行回测...' : '等待执行...'}</strong>
          </div>
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
