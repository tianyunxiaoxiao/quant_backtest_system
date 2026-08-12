import React from 'react'

const fmtPct = (v, digits = 2) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return 'NA'
  return `${(v * 100).toFixed(digits)}%`
}

const fmtNum = (v, digits = 2) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return 'NA'
  return v.toFixed(digits)
}

export default function MetricCards({ summary }) {
  if (!summary) return null
  const cards = [
    { label: '组合累计收益', value: summary.total_return, type: 'pct', positive: v => v > 0 },
    { label: '组合年化收益', value: summary.annual_return, type: 'pct', positive: v => v > 0 },
    { label: '年化波动', value: summary.annual_volatility, type: 'pct' },
    { label: 'Sharpe', value: summary.sharpe, type: 'num', positive: v => v > 0 },
    { label: '最大回撤', value: summary.max_drawdown, type: 'pct', positive: v => false },
    { label: '基准累计收益', value: summary.benchmark_total_return, type: 'pct' },
    { label: '超额累计收益', value: summary.excess_total_return_geometric, type: 'pct', positive: v => v > 0 },
    { label: '信息比率 IR', value: summary.information_ratio, type: 'num', positive: v => v > 0 },
    { label: '年化 Alpha', value: summary.alpha_annual, type: 'pct', positive: v => v > 0 },
    { label: 'Beta', value: summary.beta, type: 'num' },
  ]

  return (
    <div className="metric-grid">
      {cards.map((c, i) => {
        const raw = c.value
        const text = c.type === 'pct' ? fmtPct(raw) : fmtNum(raw)
        const isPos = c.positive ? c.positive(raw) : false
        const isNeg = c.positive === false && raw < 0
        return (
          <div key={i} className={`metric-card ${isPos ? 'positive' : ''} ${isNeg ? 'negative' : ''}`}>
            <span>{c.label}</span>
            <strong>{text}</strong>
          </div>
        )
      })}
    </div>
  )
}
