import React from 'react'

const statusText = {
  pending: '排队中',
  running: '运行中',
  completed: '完成',
  failed: '失败',
  cancelled: '已取消',
}

const formatDuration = (seconds) => {
  const value = Math.max(0, Math.floor(Number(seconds) || 0))
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const secs = value % 60
  return hours > 0
    ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
    : `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

const timingText = (run, now) => {
  if (run.status === 'pending') {
    return `排队 ${formatDuration((now - Date.parse(run.created_at)) / 1000)}`
  }
  if (run.status === 'running' && run.started_at) {
    return `运行 ${formatDuration((now - Date.parse(run.started_at)) / 1000)}`
  }
  if (run.started_at) return `耗时 ${formatDuration(run.elapsed_seconds)}`
  return null
}

const submitterText = (run) => run.owner_username ||
  (run.owner_user_id == null ? '未记录' : `用户 #${run.owner_user_id}`)

export default function RunList({ runs, selectedId, onSelect, onRefresh, onDelete, onCancel, now }) {
  return (
    <aside className="run-sidebar">
      <div className="sidebar-heading">
        <span>运行记录</span>
        <button className="icon-button" type="button" onClick={onRefresh} title="刷新">↻</button>
      </div>
      <div className="run-list">
        {runs.length === 0 && (
          <div className="empty-state" style={{ minHeight: 180 }}>
            <span>暂无运行记录</span>
          </div>
        )}
        {runs.map(run => (
          <div className="run-entry" key={run.id}>
            <button
              type="button"
              className={`run-item ${run.id === selectedId ? 'active' : ''}`}
              onClick={() => onSelect(run.id)}
            >
              <strong title={run.factor_id}>{run.factor_name || run.factor_id}</strong>
              <div className="run-meta">
                <span className={`run-state ${run.status}`}>
                  <i />{statusText[run.status] || run.status}
                </span>
                <span>{run.index_id}</span>
              </div>
              <div className="run-meta">
                <span>{run.start_date} ~ {run.end_date}</span>
                <span>{run.rebalance_frequency}</span>
              </div>
              <div className="run-meta">
                <span>提交人</span>
                <span title={submitterText(run)}>{submitterText(run)}</span>
              </div>
              {timingText(run, now) && <div className="run-timing">{timingText(run, now)}</div>}
            </button>
            <button
              type="button"
              className={`run-delete ${run.status === 'running' || run.status === 'pending' ? 'cancel' : ''}`}
              onClick={() => run.status === 'running' || run.status === 'pending'
                ? onCancel(run.id)
                : onDelete(run.id)}
            >
              {run.status === 'running' || run.status === 'pending' ? '取消' : '删除'}
            </button>
          </div>
        ))}
      </div>
    </aside>
  )
}
