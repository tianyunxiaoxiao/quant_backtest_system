import React, { useEffect, useRef } from 'react'

export default function HeatmapChart({ data, title, height = 360 }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current || !data || !data.values || data.values.length === 0) return
    const trace = {
      z: data.values,
      x: data.styles,
      y: data.years,
      type: 'heatmap',
      colorscale: 'RdYlGn',
      reversescale: true,
      hovertemplate: '%{y} / %{x}: %{z:.3f}<extra></extra>',
    }

    const layout = {
      title: { text: '', font: { size: 14, color: '#17201c' } },
      margin: { l: 60, r: 20, t: 10, b: 80 },
      xaxis: { title: '', gridcolor: '#e8ebe7', type: 'category', side: 'bottom' },
      yaxis: { title: '', gridcolor: '#e8ebe7', type: 'category', autorange: 'reversed' },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'Inter, PingFang SC, Microsoft YaHei, sans-serif' },
    }

    const config = { responsive: true, displayModeBar: false }
    window.Plotly.newPlot(ref.current, [trace], layout, config)

    return () => {
      try { window.Plotly.purge(ref.current) } catch {}
    }
  }, [data, title, height])

  if (!data || !data.values || data.values.length === 0) {
    return <div className="chart-card"><strong>{title}</strong><div className="empty-state">暂无数据</div></div>
  }

  return (
    <div className="chart-card">
      <strong>{title}</strong>
      <div ref={ref} className="plotly-chart" style={{ height }} />
    </div>
  )
}
