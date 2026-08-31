import React, { useEffect, useRef, useState } from 'react'
import {
  cancelRun,
  deleteRun,
  fetchCurrentUser,
  fetchRuns,
  login,
  logout,
  setAuthenticatedUser,
} from './api'
import ConfigForm from './components/ConfigForm'
import Dashboard from './components/Dashboard'
import RunList from './components/RunList'

const tabs = [
  { id: 'config', label: '新建回测' },
  { id: 'overview', label: '回测结果' },
  { id: 'returns', label: '收益分析' },
  { id: 'alpha_beta', label: 'Alpha / Beta' },
  { id: 'style', label: '风格暴露' },
  { id: 'costs', label: '执行成本' },
  { id: 'constraints', label: '持仓约束' },
  { id: 'positions', label: '历史持仓' },
  { id: 'report', label: '报告' },
  { id: 'artifacts', label: '产物' },
]

export default function App() {
  const [authState, setAuthState] = useState('loading')
  const [user, setUser] = useState(null)
  const [runs, setRuns] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [activeTab, setActiveTab] = useState('config')
  const [submitting, setSubmitting] = useState(false)
  const [toast, setToast] = useState(null)
  const [now, setNow] = useState(Date.now())
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
    fetchCurrentUser()
      .then(({ user: currentUser }) => {
        setUser(currentUser)
        setAuthState('authenticated')
      })
      .catch(() => {
        setAuthenticatedUser(null)
        setAuthState('anonymous')
      })
    const expired = () => {
      setUser(null)
      setAuthState('anonymous')
    }
    window.addEventListener('qbt-auth-expired', expired)
    return () => window.removeEventListener('qbt-auth-expired', expired)
  }, [])

  useEffect(() => {
    if (authState !== 'authenticated') return undefined
    loadRuns()
    pollRef.current = setInterval(loadRuns, 3000)
    const clock = setInterval(() => setNow(Date.now()), 1000)
    return () => {
      clearInterval(pollRef.current)
      clearInterval(clock)
    }
  }, [authState])

  const handleLogin = async (username, password) => {
    const auth = await login(username, password)
    setUser(auth.user)
    setAuthState('authenticated')
  }

  const handleLogout = async () => {
    try {
      await logout()
    } finally {
      setRuns([])
      setSelectedId(null)
      setUser(null)
      setAuthState('anonymous')
    }
  }

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
      if (current && ['completed', 'failed', 'cancelled'].includes(current.status)) {
        clearInterval(check)
        setSubmitting(false)
        if (current.status === 'completed') showToast('回测完成')
        else if (current.status === 'cancelled') showToast('回测已取消')
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

  const handleCancel = async (id) => {
    if (!window.confirm('确定取消这次回测吗？正在执行的计算会立即停止。')) return
    try {
      await cancelRun(id)
      setSubmitting(false)
      await loadRuns()
      showToast('回测已取消')
    } catch (err) {
      showToast('取消失败: ' + (err.response?.data?.detail || err.message), true)
    }
  }

  const renderMain = () => {
    if (activeTab === 'config') {
      return (
        <div className="view active">
          <div className="content-section config-content-section">
            <div className="section-heading"><h2>新建回测</h2></div>
            <ConfigForm onSubmitted={handleSubmitted} disabled={submitting} />
          </div>
        </div>
      )
    }
    return <Dashboard run={selectedRun} activeTab={activeTab} now={now} onCancel={handleCancel} />
  }

  if (authState === 'loading') {
    return <div className="auth-loading">正在连接统一认证...</div>
  }

  if (authState === 'anonymous') {
    return <LoginScreen onLogin={handleLogin} />
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
          <div className="current-user">
            <strong>{user?.username}</strong>
            <span>{user?.role === 'admin' ? '管理员' : '研究员'}</span>
          </div>
          <button className="primary-button" type="button" onClick={() => setActiveTab('config')} disabled={submitting}>
            {submitting ? '运行中...' : '新建回测'}
          </button>
          <button className="icon-button logout-button" type="button" onClick={handleLogout} title="退出登录" aria-label="退出登录">
            &#x21AA;
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
          onCancel={handleCancel}
          now={now}
        />
        <main className="workspace">{renderMain()}</main>
      </div>

      {toast && (
        <div className={`toast show ${toast.isError ? 'error' : ''}`}>{toast.message}</div>
      )}
    </div>
  )
}

function LoginScreen({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [working, setWorking] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setWorking(true)
    setError('')
    try {
      await onLogin(username.trim(), password)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || '登录失败')
    } finally {
      setWorking(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="login-brand">
          <span className="brand-mark">Q</span>
          <div>
            <strong>量化研究平台</strong>
            <span>统一账户中心</span>
          </div>
        </div>
        <div className="login-heading">
          <h1>登录回测工作台</h1>
          <p>使用因子研究平台账号</p>
        </div>
        <form onSubmit={submit} className="login-form">
          <label>
            <span>用户名</span>
            <input value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" autoFocus required />
          </label>
          <label>
            <span>密码</span>
            <input type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" required />
          </label>
          {error && <div className="login-error" role="alert">{error}</div>}
          <button className="primary-button login-submit" type="submit" disabled={working}>
            {working ? '正在验证...' : '登录'}
          </button>
        </form>
      </section>
    </main>
  )
}
