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

const UploadIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" />
  </svg>
)

const TrashIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5" />
  </svg>
)

const CloseIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
)

export default function ConfigForm({ onSubmitted, disabled }) {
  const [factors, setFactors] = useState([])
  const [indexes, setIndexes] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState(null)
  const [uploadFile, setUploadFile] = useState(null)
  const [dragActive, setDragActive] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const fileRef = useRef(null)
  const [uploadForm, setUploadForm] = useState({
    name: '', direction: '1', source: '', value_type: 'factor_scores',
  })
  const [form, setForm] = useState({
    factor_id: 'reversal_20d',
    factor_source: 'demo',
    factor_direction: undefined,
    factor_version_id: undefined,
    portfolio_input_mode: 'factor_scores',
    lookback: 20,
    index_id: 'ALL_A_EQ',
    start_date: '2019-01-01',
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
    min_commission: 5,           // 元/笔
    stamp_duty_rate: '',         // % (空=时变)
    transfer_fee_rate: '',       // % (空=时变)
  })

  const loadFactors = () => fetchFactors().then(setFactors)

  useEffect(() => {
    loadFactors()
    fetchIndexes().then(setIndexes)
    fetchConfig().then(c => {
      setForm(f => ({
        ...f,
        start_date: '2019-01-01',
        end_date: c.default_end || f.end_date,
        initial_capital: c.default_capital || f.initial_capital,
      }))
    })

    const refreshFactors = () => loadFactors().catch(() => {})
    const refreshVisibleFactors = () => {
      if (!document.hidden) refreshFactors()
    }
    window.addEventListener('focus', refreshFactors)
    document.addEventListener('visibilitychange', refreshVisibleFactors)
    return () => {
      window.removeEventListener('focus', refreshFactors)
      document.removeEventListener('visibilitychange', refreshVisibleFactors)
    }
  }, [])

  useEffect(() => {
    if (!importOpen) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape' && !uploading) setImportOpen(false)
    }
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [importOpen, uploading])

  const platformFactors = factors.filter(f => f.kind === 'platform')
  const importedFactors = factors.filter(f => f.kind === 'values')
  const demoFactors = factors.filter(f => f.kind === 'demo')
  const selectedFactor = factors.find(f => f.factor_id === form.factor_id)
  const isValuesFactor = selectedFactor?.kind === 'values' || selectedFactor?.kind === 'platform'
  const isDirectWeights = isValuesFactor && selectedFactor?.value_type === 'target_weights'

  const clampDatesToFactor = (f) => {
    if (!f || !['values', 'platform'].includes(f.kind)) return {}
    const patch = {}
    if (f.date_start && (!form.start_date || form.start_date < f.date_start)) patch.start_date = f.date_start
    if (f.value_type !== 'target_weights' && f.date_end && (!form.end_date || form.end_date > f.date_end)) patch.end_date = f.date_end
    return patch
  }

  const handleFactorChange = (e) => {
    const factorId = e.target.value
    const meta = factors.find(f => f.factor_id === factorId)
    const isValues = ['values', 'platform'].includes(meta?.kind)
    setForm(f => ({
      ...f,
      factor_id: factorId,
      factor_source: meta?.kind === 'platform' ? 'platform' : (isValues ? 'values' : 'demo'),
      factor_direction: isValues ? String(meta.direction || 1) : undefined,
      factor_version_id: isValues ? meta.factor_version_id : undefined,
      portfolio_input_mode: meta?.value_type === 'target_weights' ? 'direct_target_weights' : 'factor_scores',
      lookback: needsLookback[factorId] ? needsLookback[factorId].default : undefined,
      ...clampDatesToFactor(meta),
    }))
  }

  const handleUpload = async (e) => {
    e.preventDefault()
    const file = uploadFile
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
      fd.append('value_type', uploadForm.value_type)
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
        factor_version_id: created.factor_version_id,
        portfolio_input_mode: created.value_type === 'target_weights' ? 'direct_target_weights' : 'factor_scores',
        lookback: undefined,
        ...clampDatesToFactor(created),
      }))
      if (fileRef.current) fileRef.current.value = ''
      setUploadFile(null)
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
        setForm(f => ({
          ...f,
          factor_id: 'reversal_20d',
          factor_source: 'demo',
          factor_direction: undefined,
          portfolio_input_mode: 'factor_scores',
        }))
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
      min_commission: Number(form.min_commission),
      stamp_duty_rate: pctToRate(form.stamp_duty_rate),
      transfer_fee_rate: pctToRate(form.transfer_fee_rate),
      lookback: needsLookback[form.factor_id] ? Number(form.lookback) : undefined,
      factor_source: selectedFactor?.kind === 'platform' ? 'platform' : (isValuesFactor ? 'values' : 'demo'),
      factor_direction: isValuesFactor ? Number(form.factor_direction) : undefined,
      factor_version_id: isValuesFactor ? selectedFactor?.factor_version_id : undefined,
      portfolio_input_mode: isDirectWeights ? 'direct_target_weights' : 'factor_scores',
    }
    const run = await createRun(payload)
    onSubmitted(run)
  }

  return (
    <form className="config-form" onSubmit={handleSubmit}>
      <section className="config-stage">
        <div className="config-stage-heading">
          <span>01</span>
          <h3>研究标的</h3>
        </div>
        <div className="config-grid">
          <div className="form-group field-span-6">
          <label>因子</label>
          <select value={form.factor_id} onChange={handleFactorChange} disabled={disabled}>
            {platformFactors.length > 0 && (
              <optgroup label="因子研究平台">
                {platformFactors.map(f => (
                  <option key={`platform-${f.factor_id}`} value={f.factor_id}>
                    {f.factor_id}{f.name ? ` · ${f.name}` : ''}
                  </option>
                ))}
              </optgroup>
            )}
            {importedFactors.length > 0 && (
              <optgroup label="导入数据 (因子 / 权重)">
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
              {isDirectWeights ? '目标权重' : '因子值'}区间 {selectedFactor.date_start} ~ {selectedFactor.date_end} · {isDirectWeights ? '持仓密度' : '覆盖率'} {selectedFactor.coverage_ratio != null ? `${(selectedFactor.coverage_ratio * 100).toFixed(2)}%` : '-'}
            </span>
          )}
          </div>
          {isDirectWeights ? (
          <div className="form-group field-span-3">
            <label>组合输入</label>
            <div className="direct-mode-value">直接目标权重</div>
            <span className="field-hint">文件每行即一个信号日</span>
          </div>
        ) : isValuesFactor ? (
          <div className="form-group field-span-3">
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
          <div className="form-group field-span-3">
            <label>{needsLookback[form.factor_id].label}</label>
            <input
              type="number" min={2}
              value={form.lookback}
              onChange={e => setForm({ ...form, lookback: e.target.value })}
              disabled={disabled}
            />
          </div>
          ) : <div className="field-span-3" />}

          <div className="form-group field-span-3 factor-import-launcher">
            <label>因子数据</label>
            <button type="button" className="secondary-button factor-import-trigger" onClick={() => setImportOpen(true)} disabled={disabled}>
              <UploadIcon />
              导入因子 / 权重
            </button>
            <span>{importedFactors.length} 个已导入</span>
          </div>

          <div className="form-group field-span-4">
            <label>选股股票池</label>
            <select value={form.index_id} onChange={e => setForm({ ...form, index_id: e.target.value })} disabled={disabled}>
              {indexes.map(idx => (
                <option key={idx.index_id} value={idx.index_id}>{idx.name} ({idx.index_id})</option>
              ))}
            </select>
          </div>
          <div className="form-group field-span-2">
            <label>调仓频率</label>
            <select value={isDirectWeights ? 'target_weight_rows' : form.rebalance_frequency} onChange={e => setForm({ ...form, rebalance_frequency: e.target.value })} disabled={disabled || isDirectWeights}>
              {isDirectWeights && <option value="target_weight_rows">按权重文件日期</option>}
              <option value="daily">日度</option>
              <option value="weekly">周度</option>
              <option value="monthly">月度</option>
            </select>
          </div>
          <div className="form-group field-span-3">
            <label>开始日期</label>
            <input type="date" value={form.start_date} max={today()} onChange={e => setForm({ ...form, start_date: e.target.value })} disabled={disabled} />
          </div>
          <div className="form-group field-span-3">
            <label>结束日期</label>
            <input type="date" value={form.end_date} max={today()} onChange={e => setForm({ ...form, end_date: e.target.value })} disabled={disabled} />
          </div>
        </div>
      </section>

      {importOpen && (
        <div className="factor-import-backdrop" onMouseDown={e => {
          if (e.target === e.currentTarget && !uploading) setImportOpen(false)
        }}>
          <div className="factor-import-modal" role="dialog" aria-modal="true" aria-labelledby="factor-import-title">
            <div className="factor-import-modal-heading">
              <div>
                <h3 id="factor-import-title">导入因子或目标权重</h3>
                <span>PARQUET · 日期行 × 股票列</span>
              </div>
              <div className="factor-import-modal-actions">
                <span className="factor-count">{importedFactors.length} 个已导入</span>
                <button type="button" className="modal-close-button" title="关闭" aria-label="关闭导入窗口" disabled={uploading} onClick={() => setImportOpen(false)}>
                  <CloseIcon />
                </button>
              </div>
            </div>

            <section className="factor-import-section">

        <div className="factor-import-workbench">
          <label
            className={`factor-file-picker ${dragActive ? 'drag-active' : ''} ${uploadFile ? 'has-file' : ''}`}
            onDragEnter={e => { e.preventDefault(); setDragActive(true) }}
            onDragOver={e => e.preventDefault()}
            onDragLeave={e => { e.preventDefault(); setDragActive(false) }}
            onDrop={e => {
              e.preventDefault()
              setDragActive(false)
              const file = e.dataTransfer.files?.[0]
              if (file) setUploadFile(file)
            }}
          >
            <input
              type="file"
              accept=".parquet"
              ref={fileRef}
              disabled={disabled || uploading}
              onChange={e => setUploadFile(e.target.files?.[0] || null)}
            />
            <span className="file-picker-icon"><UploadIcon /></span>
            <span className="file-picker-copy">
              <strong>{uploadFile?.name || '选择 Parquet 文件'}</strong>
              <small>{uploadFile ? `${(uploadFile.size / 1024 / 1024).toFixed(2)} MB` : '因子值矩阵'}</small>
            </span>
            <span className="file-picker-action">浏览</span>
          </label>

          <div className="factor-import-fields">
            <div className="form-group factor-value-type-field">
              <label>数据类型</label>
              <div className="input-mode-segmented" role="group" aria-label="上传数据类型">
                <button type="button" className={uploadForm.value_type === 'factor_scores' ? 'active' : ''}
                  onClick={() => setUploadForm({ ...uploadForm, value_type: 'factor_scores' })} disabled={disabled || uploading}>因子分数</button>
                <button type="button" className={uploadForm.value_type === 'target_weights' ? 'active' : ''}
                  onClick={() => setUploadForm({ ...uploadForm, value_type: 'target_weights', direction: '1' })} disabled={disabled || uploading}>直接目标权重</button>
              </div>
              <span className="field-hint">
                {uploadForm.value_type === 'target_weights' ? '非负、每行权重和 ≤ 1，剩余为现金' : '用于横截面排序和组合构建'}
              </span>
            </div>
            <div className="form-group factor-name-field">
              <label>因子名称</label>
              <input
                type="text" placeholder="例如：国君 XGB 组合"
                value={uploadForm.name}
                onChange={e => setUploadForm({ ...uploadForm, name: e.target.value })}
                disabled={disabled || uploading}
              />
            </div>
            {uploadForm.value_type === 'factor_scores' && <div className="form-group factor-direction-field">
              <label>方向</label>
              <select
                value={uploadForm.direction}
                onChange={e => setUploadForm({ ...uploadForm, direction: e.target.value })}
                disabled={disabled || uploading}
              >
                <option value="1">+1 越大越好</option>
                <option value="-1">-1 越小越好</option>
              </select>
            </div>}
            <div className="form-group factor-source-field">
              <label>来源 <span>可选</span></label>
              <input
                type="text" placeholder="回测 run_id 或所属用户"
                value={uploadForm.source}
                onChange={e => setUploadForm({ ...uploadForm, source: e.target.value })}
                disabled={disabled || uploading}
              />
            </div>
            <button type="button" className="primary-button factor-import-button" onClick={handleUpload} disabled={disabled || uploading}>
              <UploadIcon />
              {uploading ? '导入中...' : (uploadForm.value_type === 'target_weights' ? '导入权重' : '导入因子')}
            </button>
          </div>
        </div>

        {uploadMsg && (
          <div className={`upload-msg ${uploadMsg.error ? 'error' : ''}`}>{uploadMsg.text}</div>
        )}
        {importedFactors.length > 0 && (
          <div className="imported-list">
            <div className="imported-list-heading">
              <strong>已导入数据</strong>
              <span>按最近导入排序</span>
            </div>
            <table className="data-table factor-table">
              <thead>
                <tr><th>名称</th><th>类型</th><th>数据区间</th><th>覆盖率</th><th aria-label="操作" /></tr>
              </thead>
              <tbody>
                {importedFactors.map(f => (
                  <tr key={f.factor_id}>
                    <td className="factor-identity">
                      <strong>{f.name}</strong>
                      <span>{f.factor_id}</span>
                    </td>
                    <td className={`factor-direction ${f.direction === -1 ? 'negative' : ''}`}>
                      {f.value_type === 'target_weights' ? '目标权重' : (f.direction === -1 ? '↓ 越小越好' : '↑ 越大越好')}
                    </td>
                    <td className="factor-period">{f.date_start} <i /> {f.date_end}</td>
                    <td className="factor-coverage">
                      <span>{f.coverage_ratio != null ? `${(f.coverage_ratio * 100).toFixed(2)}%` : '-'}</span>
                      <i style={{ '--coverage': `${Math.max(0, Math.min(100, (f.coverage_ratio || 0) * 100))}%` }} />
                    </td>
                    <td className="factor-action">
                      <button type="button" className="delete-icon-button" title={`删除 ${f.name}`} aria-label={`删除 ${f.name}`} disabled={disabled || uploading}
                        onClick={() => handleDeleteFactorValue(f.factor_id)}><TrashIcon /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
            </section>
          </div>
        </div>
      )}

      <section className="config-stage">
        <div className="config-stage-heading">
          <span>02</span>
          <h3>组合构建</h3>
        </div>
        <div className="config-grid">
        <div className="form-group field-span-3">
          <label>初始资金</label>
          <input type="number" min={1000} step={1000} value={form.initial_capital} onChange={e => setForm({ ...form, initial_capital: e.target.value })} disabled={disabled} />
        </div>
        {isDirectWeights ? (
        <div className="direct-weight-summary field-span-9">
          <strong>严格使用上传权重</strong>
          <span>不排序、不归一化、不套用单票上限；正权重需属于当日研究股票池，成交约束仍正常生效。</span>
        </div>
        ) : <>
        <div className="form-group field-span-3">
          <label>选股比例</label>
          <input type="number" min={0.01} max={1} step={0.01} value={form.selection_fraction} onChange={e => setForm({ ...form, selection_fraction: e.target.value })} disabled={disabled} />
        </div>
        <div className="form-group field-span-3">
          <label>权重方法</label>
          <select value={form.weighting_method} onChange={e => setForm({ ...form, weighting_method: e.target.value })} disabled={disabled}>
            <option value="factor_strength">因子强度</option>
            <option value="equal_weight">等权</option>
            <option value="index_weight">指数权重</option>
          </select>
        </div>
        <div className="form-group field-span-3">
          <label>单票上限</label>
          <input type="number" min={0.001} max={1} step={0.001} value={form.max_single_weight} onChange={e => setForm({ ...form, max_single_weight: e.target.value })} disabled={disabled} />
        </div>
        </>}
        </div>
      </section>

      <section className="config-stage">
        <div className="config-stage-heading">
          <span>03</span>
          <h3>交易执行</h3>
        </div>
        <div className="config-grid">
        <div className="form-group field-span-4">
          <label>成交价字段</label>
          <select value={form.fill_price_field} onChange={e => setForm({ ...form, fill_price_field: e.target.value })} disabled={disabled}>
            <option value="adj_vwap">VWAP (默认)</option>
            <option value="adj_open">开盘价</option>
            <option value="adj_close">收盘价</option>
          </select>
        </div>
        <div className="form-group field-span-4">
          <label>滑点 (bps)</label>
          <input type="number" min={0} step={0.5} value={form.slippage_bps} onChange={e => setForm({ ...form, slippage_bps: e.target.value })} disabled={disabled} />
        </div>
        <div className="form-group field-span-4">
          <label>佣金率 (%)</label>
          <input type="number" min={0} step={0.001} value={form.commission_rate} onChange={e => setForm({ ...form, commission_rate: e.target.value })} disabled={disabled} />
          <span className="field-hint">双边; 默认 0.025%</span>
        </div>
        <div className="form-group field-span-4">
          <label>最低佣金 (元/笔)</label>
          <input type="number" min={0} step={1} value={form.min_commission} onChange={e => setForm({ ...form, min_commission: e.target.value })} disabled={disabled} />
          <span className="field-hint">默认 5 元; 设为 0 可关闭</span>
        </div>
        <div className="form-group field-span-4">
          <label>印花税率 (%) — 卖出</label>
          <input type="number" min={0} step={0.001} placeholder="留空=官方时变" value={form.stamp_duty_rate} onChange={e => setForm({ ...form, stamp_duty_rate: e.target.value })} disabled={disabled} />
          <span className="field-hint">留空用官方档位: 2023-08-28 前 0.1%, 之后 0.05%</span>
        </div>
        <div className="form-group field-span-4">
          <label>过户费率 (%)</label>
          <input type="number" min={0} step={0.0001} placeholder="留空=官方时变" value={form.transfer_fee_rate} onChange={e => setForm({ ...form, transfer_fee_rate: e.target.value })} disabled={disabled} />
          <span className="field-hint">留空用官方档位: 2022-04-29 前 0.002%, 之后 0.001%</span>
        </div>
        </div>
      </section>

      <div className="form-actions">
        <div className="run-summary">
          <strong>{selectedFactor?.name || selectedFactor?.factor_id || form.factor_id}</strong>
          <span>{form.start_date} ~ {form.end_date} · {isDirectWeights ? '按权重文件日期调仓' : form.rebalance_frequency}</span>
        </div>
        <button type="submit" className="primary-button run-backtest-button" disabled={disabled}>
          {disabled ? '运行中...' : '运行回测'}
        </button>
      </div>
    </form>
  )
}
