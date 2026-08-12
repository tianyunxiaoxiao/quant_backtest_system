import React from 'react'

const statusText = {
  pending: '排队中',
  running: '运行中',
  completed: '完成',
  failed: '失败',
}

export default function RunList({ runs, selectedId, onSelect, onRefresh, onDelete }) {
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
              <strong>{run.factor_id}</strong>
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
            </button>
            <button
              type="button"
              className="run-delete"
              disabled={run.status === 'running' || run.status === 'pending'}
              onClick={() => onDelete(run.id)}
            >
              删除
            </button>
          </div>
        ))}
      </div>
    </aside>
  )
}
