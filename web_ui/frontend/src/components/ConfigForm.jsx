import React, { useEffect, useRef, useState } from 'react'
import {
  fetchConfig, fetchFactors, fetchIndexes, createRun,
  uploadFactorValue, deleteFactorValue,
} from '../api'

const needsLookback = {
  reversal_20d: { label: '回看窗口 (日)', default: 20 },
  turnover_21d: { label: '回看窗口 (日)', default: 21 },
  volatility_252d: { label: '回看窗口 (日)', default: 252 },
}

const today = () => new Date().toISOString().slice(0, 10)

export default function ConfigForm({ onSubmitted, disabled }) {
  const [factors, setFactors] = useState([])
  const [indexes, setIndexes] = useState([])
  const [config, setConfig] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState(null)
  const fileRef = useRef(null)
  const [uploadForm, setUploadForm] = useState({ name: '', direction: '1', source: '' })
  const [form, setForm] = useState({
    factor_id: 'reversal_20d',
    factor_source: 'demo',
    factor_direction: undefined,
    lookback: 20,
    index_id: 'ALL_A_EQ',
    start_date: '2018-01-01',
    end_date: '2026-03-31',
    rebalance_frequency: 'monthly',
    initial_capital: 100000000,
    selection_fraction: 0.3,
    weighting_method: 'factor_strength',
    max_single_weight: 0.05,
    fill_price_field: 'adj_vwap',
    // 交易费用: 滑点/佣金直接数值; 印花税/过户费以 % 输入, 留空 = 官方时变档位
    slippage_bps: 12,
    commission_rate: 0.025,      // %
    stamp_duty_rate: '',         // % (空=时变)
    transfer_fee_rate: '',       // % (空=时变)
  })

  const loadFactors = () => fetchFactors().then(setFactors)

  useEffect(() => {
    loadFactors()
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

  const importedFactors = factors.filter(f => f.kind === 'values')
  const demoFactors = factors.filter(f => f.kind !== 'values')
  const selectedFactor = factors.find(f => f.factor_id === form.factor_id)
  const isValuesFactor = selectedFactor?.kind === 'values'

  const clampDatesToFactor = (f) => {
    if (!f || f.kind !== 'values') return {}
    const patch = {}
    if (f.date_start && (!form.start_date || form.start_date < f.date_start)) patch.start_date = f.date_start
    if (f.date_end && (!form.end_date || form.end_date > f.date_end)) patch.end_date = f.date_end
    return patch
  }

  const handleFactorChange = (e) => {
    const factorId = e.target.value
    const meta = factors.find(f => f.factor_id === factorId)
    const isValues = meta?.kind === 'values'
    setForm(f => ({
      ...f,
      factor_id: factorId,
      factor_source: isValues ? 'values' : 'demo',
      factor_direction: isValues ? String(meta.direction || 1) : undefined,
      lookback: needsLookback[factorId] ? needsLookback[factorId].default : undefined,
      ...clampDatesToFactor(meta),
    }))
  }

  const handleUpload = async (e) => {
    e.preventDefault()
    const file = fileRef.current?.files?.[0]
    if (!file) {
      setUploadMsg({ text: '请选择 .parquet 因子值文件', error: true })
      return
    }
    if (!uploadForm.name.trim()) {
      setUploadMsg({ text: '请填写因子名称', error: true })
      return
    }
    setUploading(true)
    setUploadMsg(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('name', uploadForm.name.trim())
      fd.append('direction', uploadForm.direction)
      fd.append('source', uploadForm.source.trim())
      const created = await uploadFactorValue(fd)
      setUploadMsg({
        text: `导入成功: ${created.factor_id} (${created.n_dates} 日 × ${created.n_assets} 资产, ${created.date_start} ~ ${created.date_end})`,
        error: false,
      })
      await loadFactors()
      // 自动选中新导入的因子并适配日期区间与方向
      setForm(f => ({
        ...f,
        factor_id: created.factor_id,
        factor_source: 'values',
        factor_direction: String(created.direction),
        lookback: undefined,
        ...clampDatesToFactor(created),
      }))
      if (fileRef.current) fileRef.current.value = ''
      setUploadForm(u => ({ ...u, name: '', source: '' }))
    } catch (err) {
      const detail = err?.response?.data?.detail || err.message
      setUploadMsg({ text: '导入失败: ' + detail, error: true })
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteFactorValue = async (factorId) => {
    if (!window.confirm(`确定删除导入因子 ${factorId} 吗？`)) return
    try {
      await deleteFactorValue(factorId)
      await loadFactors()
      if (form.factor_id === factorId) {
        setForm(f => ({ ...f, factor_id: 'reversal_20d', factor_source: 'demo', factor_direction: undefined }))
      }
      setUploadMsg({ text: '已删除', error: false })
    } catch (err) {
      setUploadMsg({ text: '删除失败: ' + err.message, error: true })
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const pctToRate = (v) => (v === '' || v === null || v === undefined ? null : Number(v) / 100)
    const payload = {
      ...form,
      initial_capital: Number(form.initial_capital),
      selection_fraction: Number(form.selection_fraction),
      max_single_weight: Number(form.max_single_weight),
      slippage_bps: Number(form.slippage_bps),
      commission_rate: Number(form.commission_rate) / 100,
      stamp_duty_rate: pctToRate(form.stamp_duty_rate),
      transfer_fee_rate: pctToRate(form.transfer_fee_rate),
      lookback: needsLookback[form.factor_id] ? Number(form.lookback) : undefined,
      factor_source: isValuesFactor ? 'values' : 'demo',
      factor_direction: isValuesFactor ? Number(form.factor_direction) : undefined,
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
            {importedFactors.length > 0 && (
              <optgroup label="导入因子值 (已算好)">
                {importedFactors.map(f => (
                  <option key={f.factor_id} value={f.factor_id}>
                    {f.factor_id}{f.name ? ` · ${f.name}` : ''}
                  </option>
                ))}
              </optgroup>
            )}
            <optgroup label="内置公式因子">
              {demoFactors.map(f => (
                <option key={f.factor_id} value={f.factor_id}>{f.factor_id}</option>
              ))}
            </optgroup>
          </select>
          {selectedFactor?.kind === 'values' && (
            <span className="field-hint">
              因子值区间 {selectedFactor.date_start} ~ {selectedFactor.date_end} · 覆盖率 {selectedFactor.coverage_ratio != null ? `${(selectedFactor.coverage_ratio * 100).toFixed(1)}%` : '-'}
            </span>
          )}
        </div>
        {isValuesFactor ? (
          <div className="form-group">
            <label>因子方向 (回测前声明)</label>
            <select
              value={form.factor_direction ?? '1'}
              onChange={e => setForm({ ...form, factor_direction: e.target.value })}
              disabled={disabled}
            >
              <option value="1">+1 越大越好</option>
              <option value="-1">-1 越小越好</option>
            </select>
          </div>
        ) : needsLookback[form.factor_id] ? (
          <div className="form-group">
            <label>{needsLookback[form.factor_id].label}</label>
            <input
              type="number" min={2}
              value={form.lookback}
              onChange={e => setForm({ ...form, lookback: e.target.value })}
              disabled={disabled}
            />
          </div>
        ) : null}
      </div>

      <div className="content-section upload-panel">
        <div className="section-heading">
          <h3>导入因子值 (parquet: 日期行 × 股票列)</h3>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label>因子值文件 (.parquet)</label>
            <input type="file" accept=".parquet" ref={fileRef} disabled={disabled || uploading} />
          </div>
          <div className="form-group">
            <label>因子名称</label>
            <input
              type="text" placeholder="如 gj_alpha80反向"
              value={uploadForm.name}
              onChange={e => setUploadForm({ ...uploadForm, name: e.target.value })}
              disabled={disabled || uploading}
            />
          </div>
          <div className="form-group">
            <label>方向</label>
            <select
              value={uploadForm.direction}
              onChange={e => setUploadForm({ ...uploadForm, direction: e.target.value })}
              disabled={disabled || uploading}
            >
              <option value="1">+1 越大越好</option>
              <option value="-1">-1 越小越好</option>
            </select>
          </div>
          <div className="form-group">
            <label>来源 (可选)</label>
            <input
              type="text" placeholder="如 来源回测 run_id / 所属用户"
              value={uploadForm.source}
              onChange={e => setUploadForm({ ...uploadForm, source: e.target.value })}
              disabled={disabled || uploading}
            />
          </div>
        </div>
        <div className="form-actions">
          <button type="button" className="primary-button" onClick={handleUpload} disabled={disabled || uploading}>
            {uploading ? '导入中...' : '上传导入'}
          </button>
        </div>
        {uploadMsg && (
          <div className={`upload-msg ${uploadMsg.error ? 'error' : ''}`}>{uploadMsg.text}</div>
        )}
        {importedFactors.length > 0 && (
          <div className="imported-list">
            <table className="data-table">
              <thead>
                <tr><th>因子ID</th><th>名称</th><th>方向</th><th>区间</th><th>覆盖</th><th>操作</th></tr>
              </thead>
              <tbody>
                {importedFactors.map(f => (
                  <tr key={f.factor_id}>
                    <td>{f.factor_id}</td>
                    <td>{f.name}</td>
                    <td>{f.direction === -1 ? '-1' : '+1'}</td>
                    <td>{f.date_start} ~ {f.date_end}</td>
                    <td>{f.coverage_ratio != null ? `${(f.coverage_ratio * 100).toFixed(1)}%` : '-'}</td>
                    <td>
                      <button type="button" className="ghost-button" disabled={disabled || uploading}
                        onClick={() => handleDeleteFactorValue(f.factor_id)}>删除</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
          <input type="date" value={form.start_date} max={today()} onChange={e => setForm({ ...form, start_date: e.target.value })} disabled={disabled} />
        </div>
        <div className="form-group">
          <label>结束日期</label>
          <input type="date" value={form.end_date} max={today()} onChange={e => setForm({ ...form, end_date: e.target.value })} disabled={disabled} />
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

      <div className="form-row">
        <div className="form-group">
          <label>佣金率 (%)</label>
          <input type="number" min={0} step={0.001} value={form.commission_rate} onChange={e => setForm({ ...form, commission_rate: e.target.value })} disabled={disabled} />
          <span className="field-hint">双边; 默认 0.025%</span>
        </div>
        <div className="form-group">
          <label>印花税率 (%) — 卖出</label>
          <input type="number" min={0} step={0.001} placeholder="留空=官方时变" value={form.stamp_duty_rate} onChange={e => setForm({ ...form, stamp_duty_rate: e.target.value })} disabled={disabled} />
          <span className="field-hint">留空用官方档位: 2023-08-28 前 0.1%, 之后 0.05%</span>
        </div>
        <div className="form-group">
          <label>过户费率 (%)</label>
          <input type="number" min={0} step={0.0001} placeholder="留空=官方时变" value={form.transfer_fee_rate} onChange={e => setForm({ ...form, transfer_fee_rate: e.target.value })} disabled={disabled} />
          <span className="field-hint">留空用官方档位: 2022-04-29 前 0.002%, 之后 0.001%</span>
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
