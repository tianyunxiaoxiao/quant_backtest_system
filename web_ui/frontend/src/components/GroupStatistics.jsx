import React, { useEffect, useMemo, useState } from 'react'
import { fetchBenchmarks, fetchGroupStatistics } from '../api'

const DEFAULT_BENCHMARK_ID = '000852.SH'
const FREQUENCY_LABELS = {
  daily: '日度',
  weekly: '周度',
  monthly: '月度',
  target_weight_rows: '按权重文件日期',
}

const columns = [
  { key: 'display_name', label: '回测名称', type: 'text', value: row => row.display_name },
  { key: 'rebalance_frequency', label: '调仓频率', type: 'text', value: row => FREQUENCY_LABELS[row.rebalance_frequency] || row.rebalance_frequency || '' },
  { key: 'period', label: '回测区间', type: 'text', value: row => `${row.start_date || ''} ~ ${row.end_date || ''}` },
  { key: 'total_return', label: '组合累计收益', type: 'pct' },
  { key: 'annual_return', label: '组合年化收益', type: 'pct' },
  { key: 'annual_volatility', label: '年化波动', type: 'pct' },
  { key: 'sharpe', label: 'Sharpe', type: 'num' },
  { key: 'max_drawdown', label: '最大回撤', type: 'pct' },
  { key: 'excess_annual_return_geometric', label: '超额年化', type: 'pct' },
  { key: 'excess_sharpe', label: '超额夏普', type: 'num' },
  { key: 'excess_max_drawdown', label: '超额最大回撤', type: 'pct' },
  { key: 'excess_volatility', label: '超额波动率', type: 'pct' },
  { key: 'information_ratio', label: '信息比率 IR', type: 'num' },
]

const rawValue = (row, column) => column.value ? column.value(row) : row.metrics?.[column.key]
const formatValue = (value, type) => {
  if (type === 'text') return value || 'NA'
  if (value === null || value === undefined || !Number.isFinite(value)) return 'NA'
  return type === 'pct' ? `${(value * 100).toFixed(2)}%` : value.toFixed(2)
}

export default function GroupStatistics({ group, onSelectRun }) {
  const [benchmarks, setBenchmarks] = useState([])
  const [benchmarkId, setBenchmarkId] = useState(DEFAULT_BENCHMARK_ID)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sort, setSort] = useState({ key: null, direction: null })
  const groupIds = group?.ids || null
  const groupKey = groupIds?.join(',') || 'all'

  useEffect(() => {
    fetchBenchmarks()
      .then(items => setBenchmarks(Array.isArray(items) ? items : []))
      .catch(() => setBenchmarks([]))
  }, [])

  useEffect(() => {
    let current = true
    setLoading(true)
    setError('')
    fetchGroupStatistics(benchmarkId, groupIds)
      .then(result => {
        if (!current) return
        setRows(Array.isArray(result.rows) ? result.rows : [])
        setLoading(false)
      })
      .catch(err => {
        if (!current) return
        setRows([])
        setError(err.response?.data?.detail || err.message)
        setLoading(false)
      })
    return () => { current = false }
  }, [benchmarkId, groupKey])

  useEffect(() => setSort({ key: null, direction: null }), [groupKey])

  const sortedRows = useMemo(() => {
    if (!sort.key || !sort.direction) return rows
    const column = columns.find(item => item.key === sort.key)
    if (!column) return rows
    return rows
      .map((row, index) => ({ row, index }))
      .sort((left, right) => {
        const a = rawValue(left.row, column)
        const b = rawValue(right.row, column)
        const aMissing = a === null || a === undefined || a === '' || (typeof a === 'number' && !Number.isFinite(a))
        const bMissing = b === null || b === undefined || b === '' || (typeof b === 'number' && !Number.isFinite(b))
        if (aMissing !== bMissing) return aMissing ? 1 : -1
        if (aMissing && bMissing) return left.index - right.index
        const compared = column.type === 'text'
          ? String(a).localeCompare(String(b), 'zh-CN')
          : Number(a) - Number(b)
        if (compared === 0) return left.index - right.index
        return sort.direction === 'desc' ? -compared : compared
      })
      .map(item => item.row)
  }, [rows, sort])

  const changeSort = (key) => {
    setSort(current => {
      if (current.key !== key) return { key, direction: 'desc' }
      if (current.direction === 'desc') return { key, direction: 'asc' }
      if (current.direction === 'asc') return { key: null, direction: null }
      return { key, direction: 'desc' }
    })
  }

  const sortMark = (key) => {
    if (sort.key !== key) return '↕'
    return sort.direction === 'desc' ? '↓' : '↑'
  }

  return (
    <div className="view active group-statistics-page">
      <div className="group-statistics-heading">
        <div>
          <span>分组统计</span>
          <h1>{group?.name || '全部分组'}</h1>
          <p>{loading ? '正在计算...' : `${rows.length} 个已完成回测`}</p>
        </div>
        <label>
          <span>对比基准</span>
          <select value={benchmarkId} onChange={event => setBenchmarkId(event.target.value)} disabled={loading} aria-label="统计对比基准">
            {benchmarks.map(item => <option key={item.benchmark_id} value={item.benchmark_id}>{item.name} ({item.benchmark_id})</option>)}
          </select>
        </label>
      </div>

      {error && <div className="inline-error">统计加载失败：{error}</div>}
      <div className="group-statistics-table-wrap">
        <table className="group-statistics-table">
          <thead>
            <tr>
              {columns.map(column => (
                <th key={column.key}>
                  <button type="button" onClick={() => changeSort(column.key)} aria-label={`${column.label}排序`}>
                    <span>{column.label}</span><i>{sortMark(column.key)}</i>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {!loading && sortedRows.map(row => (
              <tr key={row.id} className={row.error ? 'has-warning' : ''} title={row.error || undefined}>
                {columns.map(column => {
                  const value = rawValue(row, column)
                  const content = formatValue(value, column.type)
                  const className = column.type !== 'text' && Number.isFinite(value)
                    ? value > 0 ? 'positive' : value < 0 ? 'negative' : ''
                    : ''
                  return (
                    <td key={column.key} className={className}>
                      {column.key === 'display_name'
                        ? <button type="button" className="statistics-run-link" onClick={() => onSelectRun(row.id)}>{content}</button>
                        : content}
                    </td>
                  )
                })}
              </tr>
            ))}
            {loading && <tr><td className="statistics-empty" colSpan={columns.length}>正在按所选基准计算分组统计...</td></tr>}
            {!loading && !error && rows.length === 0 && <tr><td className="statistics-empty" colSpan={columns.length}>当前分组没有已完成的回测</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
