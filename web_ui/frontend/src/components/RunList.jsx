import React, { useEffect, useMemo, useState } from 'react'

const PAGE_SIZE = 10

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
  if (run.status === 'pending') return `排队 ${formatDuration((now - Date.parse(run.created_at)) / 1000)}`
  if (run.status === 'running' && run.started_at) return `运行 ${formatDuration((now - Date.parse(run.started_at)) / 1000)}`
  if (run.started_at) return `耗时 ${formatDuration(run.elapsed_seconds)}`
  return null
}

const submitterText = (run) => run.owner_username ||
  (run.owner_user_id == null ? '未记录' : `用户 #${run.owner_user_id}`)
const runTitle = (run) => run.display_name || run.factor_name || run.factor_id

export default function RunList({
  runs,
  groups,
  displayGroups,
  groupFilter,
  onGroupFilterChange,
  canManageGroups,
  selectedId,
  onSelect,
  onRefresh,
  onDelete,
  onCancel,
  onCreateGroup,
  onRenameGroup,
  onDeleteGroup,
  onAssignGroup,
  onRenameRun,
  now,
}) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const [page, setPage] = useState(1)
  const [managerOpen, setManagerOpen] = useState(false)
  const [assignmentRunId, setAssignmentRunId] = useState(null)
  const [renameRunId, setRenameRunId] = useState(null)
  const [runName, setRunName] = useState('')
  const [newGroupName, setNewGroupName] = useState('')
  const [editingGroupId, setEditingGroupId] = useState(null)
  const [editingName, setEditingName] = useState('')
  const [working, setWorking] = useState(false)

  const groupMap = useMemo(() => new Map(groups.map(group => [group.id, group])), [groups])

  const filteredRuns = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return runs.filter(run => {
      if (status !== 'all' && run.status !== status) return false
      if (groupFilter !== 'all') {
        const selectedGroup = displayGroups.find(group => String(group.id) === groupFilter)
        if (!selectedGroup?.ids.includes(run.group_id)) return false
      }
      if (!keyword) return true
      return [
        run.factor_name,
        run.display_name,
        run.factor_id,
        run.index_id,
        submitterText(run),
        groupMap.get(run.group_id)?.name,
      ].filter(Boolean).some(value => String(value).toLowerCase().includes(keyword))
    })
  }, [runs, query, status, groupFilter, groupMap, displayGroups])

  const pageCount = Math.max(1, Math.ceil(filteredRuns.length / PAGE_SIZE))
  const pageRuns = filteredRuns.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const assignmentRun = runs.find(run => run.id === assignmentRunId) || null
  const renameTarget = runs.find(run => run.id === renameRunId) || null
  const assignmentGroups = assignmentRun
    ? groups
    : []

  useEffect(() => setPage(1), [query, status, groupFilter])
  useEffect(() => setPage(current => Math.min(current, pageCount)), [pageCount])
  useEffect(() => {
    if (groupFilter !== 'all' && !displayGroups.some(group => String(group.id) === groupFilter)) {
      onGroupFilterChange('all')
    }
  }, [groupFilter, displayGroups, onGroupFilterChange])
  useEffect(() => {
    if (!managerOpen && !assignmentRunId && !renameRunId) return undefined
    const onKeyDown = (event) => {
      if (event.key !== 'Escape' || working) return
      setManagerOpen(false)
      setAssignmentRunId(null)
      setRenameRunId(null)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [managerOpen, assignmentRunId, renameRunId, working])

  const submitNewGroup = async (event) => {
    event.preventDefault()
    const name = newGroupName.trim()
    if (!name) return
    setWorking(true)
    try {
      await onCreateGroup(name)
      setNewGroupName('')
    } catch {
      // App-level handler surfaces the API error in a toast.
    } finally {
      setWorking(false)
    }
  }

  const saveGroupName = async (groupId) => {
    const name = editingName.trim()
    if (!name) return
    setWorking(true)
    try {
      await onRenameGroup(groupId, name)
      setEditingGroupId(null)
      setEditingName('')
    } catch {
      // Keep edit mode open so the name can be corrected.
    } finally {
      setWorking(false)
    }
  }

  const removeGroup = async (group) => {
    if (!window.confirm(`删除分组“${group.name}”？组内回测结果会移至未分组。`)) return
    setWorking(true)
    try {
      await onDeleteGroup(group.id)
    } catch {
      // App-level handler surfaces the API error in a toast.
    } finally {
      setWorking(false)
    }
  }

  const assignGroup = async (groupId) => {
    if (!assignmentRun) return
    setWorking(true)
    try {
      await onAssignGroup(assignmentRun.id, groupId)
      setAssignmentRunId(null)
    } catch {
      // Keep the assignment dialog open when the update fails.
    } finally {
      setWorking(false)
    }
  }

  const saveRunName = async (event) => {
    event.preventDefault()
    const name = runName.trim()
    if (!renameTarget || !name) return
    setWorking(true)
    try {
      await onRenameRun(renameTarget.id, name)
      setRenameRunId(null)
      setRunName('')
    } catch {
      // Keep the dialog open so the name can be corrected.
    } finally {
      setWorking(false)
    }
  }

  return (
    <aside className="run-sidebar">
      <div className="sidebar-heading">
        <span>回测结果 <small>{filteredRuns.length}</small></span>
        <div className="sidebar-heading-actions">
          {canManageGroups && <button className="icon-button" type="button" onClick={() => setManagerOpen(true)} title="管理分组" aria-label="管理回测分组">+</button>}
          <button className="icon-button" type="button" onClick={onRefresh} title="刷新" aria-label="刷新回测结果">↻</button>
        </div>
      </div>

      <div className="run-filters">
        <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索结果名、因子或提交人" aria-label="搜索回测结果" />
        <div className="run-filter-field">
          <label htmlFor="run-status-filter">状态筛选：</label>
          <select id="run-status-filter" value={status} onChange={event => setStatus(event.target.value)} aria-label="按状态筛选">
            <option value="all">全部状态</option>
            {Object.entries(statusText).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
        <div className="run-filter-field">
          <label htmlFor="run-group-filter">分组选择：</label>
          <select id="run-group-filter" value={groupFilter} onChange={event => onGroupFilterChange(event.target.value)} aria-label="按分组筛选">
            <option value="all">全部分组</option>
            {displayGroups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}
          </select>
        </div>
      </div>

      <div className="run-list">
        {pageRuns.length === 0 && (
          <div className="empty-state run-list-empty"><span>{runs.length === 0 ? '暂无运行记录' : '没有符合条件的结果'}</span></div>
        )}
        {pageRuns.map(run => (
          <div className="run-entry" key={run.id}>
            <button type="button" className={`run-item ${run.id === selectedId ? 'active' : ''}`} onClick={() => onSelect(run.id)}>
              <strong title={run.display_name ? `${run.display_name} · ${run.factor_name || run.factor_id}` : run.factor_id}>{runTitle(run)}</strong>
              <div className="run-meta">
                <span className={`run-state ${run.status}`}><i />{statusText[run.status] || run.status}</span>
                <span>{run.index_id}</span>
              </div>
              <div className="run-meta"><span>{run.start_date} ~ {run.end_date}</span><span>{run.rebalance_frequency}</span></div>
              <div className="run-meta">
                <span title={submitterText(run)}>{submitterText(run)}</span>
                <span className="run-group-name">{groupMap.get(run.group_id)?.name || '未分组'}</span>
              </div>
              {timingText(run, now) && <div className="run-timing">{timingText(run, now)}</div>}
            </button>
            <div className="run-entry-actions">
              <button type="button" onClick={() => { setRenameRunId(run.id); setRunName(runTitle(run)) }}>命名</button>
              <button type="button" onClick={() => setAssignmentRunId(run.id)}>分组</button>
              <button type="button" className={run.status === 'running' || run.status === 'pending' ? 'cancel' : 'delete'} onClick={() => run.status === 'running' || run.status === 'pending' ? onCancel(run.id) : onDelete(run.id)}>
                {run.status === 'running' || run.status === 'pending' ? '取消' : '删除'}
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="run-pagination" aria-label="回测结果分页">
        <button type="button" onClick={() => setPage(value => Math.max(1, value - 1))} disabled={page === 1} aria-label="上一页">‹</button>
        <span>{page} / {pageCount}</span>
        <button type="button" onClick={() => setPage(value => Math.min(pageCount, value + 1))} disabled={page === pageCount} aria-label="下一页">›</button>
      </div>

      {managerOpen && (
        <div className="run-group-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !working) setManagerOpen(false) }}>
          <section className="run-group-modal" role="dialog" aria-modal="true" aria-labelledby="group-manager-title">
            <header>
              <div><span>结果整理</span><h2 id="group-manager-title">管理回测分组</h2></div>
              <button className="modal-close-button" type="button" onClick={() => setManagerOpen(false)} disabled={working} aria-label="关闭">×</button>
            </header>
            <form className="run-group-create" onSubmit={submitNewGroup}>
              <input value={newGroupName} onChange={event => setNewGroupName(event.target.value)} maxLength={40} placeholder="新分组名称" aria-label="新分组名称" />
              <button className="primary-button" type="submit" disabled={working || !newGroupName.trim()}>创建</button>
            </form>
            <div className="run-group-list">
              {groups.length === 0 && <div className="run-group-empty">还没有分组</div>}
              {displayGroups.map(group => (
                <div className="run-group-row" key={group.id}>
                  {editingGroupId === group.id ? (
                    <input value={editingName} onChange={event => setEditingName(event.target.value)} maxLength={40} autoFocus aria-label="编辑分组名称" />
                  ) : (
                    <div><strong>{group.name}</strong><span>{runs.filter(run => group.ids.includes(run.group_id)).length} 个结果{group.isDefault ? ' · 默认分组' : ''}</span></div>
                  )}
                  <div>
                    {group.isDefault ? null : editingGroupId === group.id ? (
                      <><button type="button" onClick={() => saveGroupName(group.id)} disabled={working || !editingName.trim()}>保存</button><button type="button" onClick={() => setEditingGroupId(null)} disabled={working}>取消</button></>
                    ) : (
                      <><button type="button" onClick={() => { setEditingGroupId(group.id); setEditingName(group.name) }}>重命名</button><button type="button" className="danger-text" onClick={() => removeGroup(group)} disabled={working}>删除</button></>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      {assignmentRun && (
        <div className="run-group-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !working) setAssignmentRunId(null) }}>
          <section className="run-group-modal run-assignment-modal" role="dialog" aria-modal="true" aria-labelledby="group-assignment-title">
            <header>
              <div><span>结果分组</span><h2 id="group-assignment-title">{runTitle(assignmentRun)}</h2></div>
              <button className="modal-close-button" type="button" onClick={() => setAssignmentRunId(null)} disabled={working} aria-label="关闭">×</button>
            </header>
            <div className="run-assignment-list">
              {assignmentGroups.map(group => (
                <button type="button" key={group.id} className={assignmentRun.group_id === group.id ? 'active' : ''} onClick={() => assignGroup(group.id)} disabled={working}><span>{group.name}</span><i>{assignmentRun.group_id === group.id ? '✓' : ''}</i></button>
              ))}
              {assignmentGroups.length === 0 && <p>请先在左上角创建分组。</p>}
            </div>
          </section>
        </div>
      )}

      {renameTarget && (
        <div className="run-group-backdrop" onMouseDown={event => { if (event.target === event.currentTarget && !working) setRenameRunId(null) }}>
          <section className="run-group-modal run-rename-modal" role="dialog" aria-modal="true" aria-labelledby="run-rename-title">
            <header>
              <div><span>结果名称</span><h2 id="run-rename-title">编辑回测结果名称</h2></div>
              <button className="modal-close-button" type="button" onClick={() => setRenameRunId(null)} disabled={working} aria-label="关闭">×</button>
            </header>
            <form className="run-rename-form" onSubmit={saveRunName}>
              <label htmlFor="run-display-name">名称</label>
              <input id="run-display-name" value={runName} onChange={event => setRunName(event.target.value)} maxLength={80} autoFocus />
              <div>
                <button className="secondary-button" type="button" onClick={() => setRenameRunId(null)} disabled={working}>取消</button>
                <button className="primary-button" type="submit" disabled={working || !runName.trim()}>保存</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </aside>
  )
}
