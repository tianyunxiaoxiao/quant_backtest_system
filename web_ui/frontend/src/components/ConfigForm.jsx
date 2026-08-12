import React, { useEffect, useState } from 'react'
import { fetchConfig, fetchFactors, fetchIndexes, createRun } from '../api'

const needsLookback = {
  reversal_20d: { label: '回看窗口 (日)', default: 20 },
  turnover_21d: { label: '回看窗口 (日)', default: 21 },
  volatility_252d: { label: '回看窗口 (日)', default: 252 },
}

export default function ConfigForm({ onSubmitted, disabled }) {
  const [factors, setFactors] = useState([])
  const [indexes, setIndexes] = useState([])
  const [config, setConfig] = useState(null)
  const [form, setForm] = useState({
    factor_id: 'reversal_20d',
    lookback: 20,
    index_id: 'ALL_A_EQ',
    start_date: '2018-01-01',
    end_date: '2026-03-31',
    rebalance_frequency: 'monthly',
    initial_capital: 100000000,
    selection_fraction: 0.3,
    weighting_method: 'factor_strength',
    max_single_weight: 0.05,
    slippage_bps: 12,
    commission_rate: 0.00025,
    fill_price_field: 'adj_vwap',
  })

  useEffect(() => {
    fetchFactors().then(setFactors)
    fetchIndexes().then(setIndexes)
    fetchConfig().then(c => {
      setConfig(c)
      setForm(f => ({
        ...f,
        start_date: c.default_start || f.start_date,
        end_date: c.default_end || f.end_date,
        initial_capital: c.default_capital || f.initial_capital,
      }))
    })
  }, [])

  const handleFactorChange = (e) => {
    const factorId = e.target.value
    const meta = needsLookback[factorId]
    setForm(f => ({
      ...f,
      factor_id: factorId,
      lookback: meta ? meta.default : undefined,
    }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const payload = {
      ...form,
      initial_capital: Number(form.initial_capital),
      selection_fraction: Number(form.selection_fraction),
      max_single_weight: Number(form.max_single_weight),
      slippage_bps: Number(form.slippage_bps),
      commission_rate: Number(form.commission_rate),
      lookback: needsLookback[form.factor_id] ? Number(form.lookback) : undefined,
    }
    const run = await createRun(payload)
    onSubmitted(run)
  }

  return (
    <form className="config-form" onSubmit={handleSubmit}>
      <div className="form-row">
        <div className="form-group">
          <label>因子</label>
          <select value={form.factor_id} onChange={handleFactorChange} disabled={disabled}>
            {factors.map(f => (
              <option key={f.factor_id} value={f.factor_id}>{f.factor_id}</option>
            ))}
          </select>
        </div>
        {needsLookback[form.factor_id] && (
          <div className="form-group">
            <label>{needsLookback[form.factor_id].label}</label>
            <input
              type="number"
              min={2}
              value={form.lookback}
              onChange={e => setForm({ ...form, lookback: e.target.value })}
              disabled={disabled}
            />
          </div>
        )}
      </div>

      <div className="form-row">
        <div className="form-group">
          <label>基准指数</label>
          <select value={form.index_id} onChange={e => setForm({ ...form, index_id: e.target.value })} disabled={disabled}>
            {indexes.map(idx => (
              <option key={idx.index_id} value={idx.index_id}>{idx.name} ({idx.index_id})</option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label>调仓频率</label>
          <select value={form.rebalance_frequency} onChange={e => setForm({ ...form, rebalance_frequency: e.target.value })} disabled={disabled}>
            <option value="daily">日度</option>
            <option value="weekly">周度</option>
            <option value="monthly">月度</option>
          </select>
        </div>
      </div>

      <div className="form-row">
        <div className="form-group">
          <label>开始日期</label>
          <input type="date" value={form.start_date} onChange={e => setForm({ ...form, start_date: e.target.value })} disabled={disabled} />
        </div>
        <div className="form-group">
          <label>结束日期</label>
          <input type="date" value={form.end_date} onChange={e => setForm({ ...form, end_date: e.target.value })} disabled={disabled} />
        </div>
      </div>

      <div className="form-row">
        <div className="form-group">
          <label>初始资金</label>
          <input type="number" min={1000} step={1000} value={form.initial_capital} onChange={e => setForm({ ...form, initial_capital: e.target.value })} disabled={disabled} />
        </div>
        <div className="form-group">
          <label>选股比例</label>
          <input type="number" min={0.01} max={1} step={0.01} value={form.selection_fraction} onChange={e => setForm({ ...form, selection_fraction: e.target.value })} disabled={disabled} />
        </div>
      </div>

      <div className="form-row">
        <div className="form-group">
          <label>权重方法</label>
          <select value={form.weighting_method} onChange={e => setForm({ ...form, weighting_method: e.target.value })} disabled={disabled}>
            <option value="factor_strength">因子强度</option>
            <option value="equal_weight">等权</option>
            <option value="index_weight">指数权重</option>
          </select>
        </div>
        <div className="form-group">
          <label>单票上限</label>
          <input type="number" min={0.001} max={1} step={0.001} value={form.max_single_weight} onChange={e => setForm({ ...form, max_single_weight: e.target.value })} disabled={disabled} />
        </div>
      </div>

      <div className="form-row">
        <div className="form-group">
          <label>成交价字段</label>
          <select value={form.fill_price_field} onChange={e => setForm({ ...form, fill_price_field: e.target.value })} disabled={disabled}>
            <option value="adj_vwap">VWAP (默认)</option>
            <option value="adj_open">开盘价</option>
            <option value="adj_close">收盘价</option>
          </select>
        </div>
        <div className="form-group">
          <label>滑点 (bps)</label>
          <input type="number" min={0} step={0.5} value={form.slippage_bps} onChange={e => setForm({ ...form, slippage_bps: e.target.value })} disabled={disabled} />
        </div>
      </div>

      <div className="form-actions">
        <button type="submit" className="primary-button" disabled={disabled}>
          {disabled ? '运行中...' : '▶ 运行回测'}
        </button>
      </div>
    </form>
  )
}
