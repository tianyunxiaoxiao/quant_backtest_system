import React, { useEffect, useRef, useState } from 'react'
import { deleteRun, fetchRuns } from './api'
import ConfigForm from './components/ConfigForm'
import Dashboard from './components/Dashboard'
import RunList from './components/RunList'

const tabs = [
  { id: 'config', label: '新建回测' },
  { id: 'overview', label: '概览' },
  { id: 'returns', label: '收益分析' },
  { id: 'alpha_beta', label: 'Alpha / Beta' },
  { id: 'style', label: '风格暴露' },
  { id: 'costs', label: '执行成本' },
  { id: 'constraints', label: '持仓约束' },
  { id: 'report', label: '报告' },
  { id: 'artifacts', label: '产物' },
]

export default function App() {
  const [runs, setRuns] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [activeTab, setActiveTab] = useState('config')
  const [submitting, setSubmitting] = useState(false)
  const [toast, setToast] = useState(null)
  const pollRef = useRef(null)

  const selectedRun = runs.find(r => r.id === selectedId) || null

  const loadRuns = async () => {
    try {
      const data = await fetchRuns()
      setRuns(data)
    } catch (err) {
      showToast('加载运行记录失败: ' + err.message, true)
    }
  }

  useEffect(() => {
    loadRuns()
    pollRef.current = setInterval(loadRuns, 3000)
    return () => clearInterval(pollRef.current)
  }, [])

  const showToast = (message, isError = false) => {
    setToast({ message, isError })
    setTimeout(() => setToast(null), 3600)
  }

  const handleSubmitted = (run) => {
    setSubmitting(true)
    loadRuns()
    setSelectedId(run.id)
    setActiveTab('overview')
    // Wait until run completes before re-enabling form.
    const check = setInterval(async () => {
      const list = await fetchRuns()
      setRuns(list)
      const current = list.find(r => r.id === run.id)
      if (current && (current.status === 'completed' || current.status === 'failed')) {
        clearInterval(check)
        setSubmitting(false)
        if (current.status === 'completed') showToast('回测完成')
        else showToast('回测失败: ' + (current.error || ''), true)
      }
    }, 2000)
    // Safety timeout
    setTimeout(() => {
      clearInterval(check)
      setSubmitting(false)
    }, 600000)
  }

  const handleSelect = (id) => {
    setSelectedId(id)
    setActiveTab('overview')
  }

  const handleDelete = async (id) => {
    if (!window.confirm('确定删除该运行记录及其产物吗？')) return
    try {
      await deleteRun(id)
      if (selectedId === id) setSelectedId(null)
      await loadRuns()
      showToast('已删除')
    } catch (err) {
      showToast('删除失败: ' + err.message, true)
    }
  }

  const renderMain = () => {
    if (activeTab === 'config') {
      return (
        <div className="view active">
          <div className="content-section">
            <div className="section-heading"><h2>新建回测</h2></div>
            <ConfigForm onSubmitted={handleSubmitted} disabled={submitting} />
          </div>
        </div>
      )
    }
    return <Dashboard run={selectedRun} activeTab={activeTab} />
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">Q</span>
          <div>
            <strong>量化回测可视化</strong>
            <span>Long-Only Factor Backtest</span>
          </div>
        </div>

        <nav className="top-tabs">
          {tabs.map(t => (
            <button
              key={t.id}
              type="button"
              className={`top-tab ${activeTab === t.id ? 'active' : ''}`}
              onClick={() => setActiveTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div className="top-actions">
          <button className="primary-button" type="button" onClick={() => setActiveTab('config')} disabled={submitting}>
            {submitting ? '运行中...' : '新建回测'}
          </button>
        </div>
      </header>

      <div className="app-shell">
        <RunList
          runs={runs}
          selectedId={selectedId}
          onSelect={handleSelect}
          onRefresh={loadRuns}
          onDelete={handleDelete}
        />
        <main className="workspace">{renderMain()}</main>
      </div>

      {toast && (
        <div className={`toast show ${toast.isError ? 'error' : ''}`}>{toast.message}</div>
      )}
    </div>
  )
}
