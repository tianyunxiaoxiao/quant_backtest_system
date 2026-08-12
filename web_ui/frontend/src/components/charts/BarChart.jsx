import React, { useEffect, useRef } from 'react'

const colorPalette = ['#176b4d', '#315f83', '#9a6400', '#ad3e2d', '#6b4c9a']

export default function BarChart({ data, title, yLabel, height = 360, percentAxis = true }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current || !data || !data.series || data.series.length === 0) return
    const traces = data.series.map((s, i) => ({
      x: data.categories,
      y: s.values,
      type: 'bar',
      name: s.name,
      marker: { color: colorPalette[i % colorPalette.length] },
      hovertemplate: '%{data.name}: %{y:.2%}<extra></extra>',
    }))

    const layout = {
      title: { text: '', font: { size: 14, color: '#17201c' } },
      margin: { l: 50, r: 20, t: 10, b: 60 },
      xaxis: { title: '', gridcolor: '#e8ebe7', tickangle: -45 },
      yaxis: { title: yLabel || '', gridcolor: '#e8ebe7', tickformat: percentAxis ? '.1%' : '' },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      legend: { x: 0, y: 1.15, orientation: 'h' },
      barmode: 'group',
      font: { family: 'Inter, PingFang SC, Microsoft YaHei, sans-serif' },
    }

    const config = { responsive: true, displayModeBar: false }
    window.Plotly.newPlot(ref.current, traces, layout, config)

    return () => {
      try { window.Plotly.purge(ref.current) } catch {}
    }
  }, [data, title, yLabel, height, percentAxis])

  if (!data || !data.series || data.series.length === 0) {
    return <div className="chart-card"><strong>{title}</strong><div className="empty-state">暂无数据</div></div>
  }

  return (
    <div className="chart-card">
      <strong>{title}</strong>
      <div ref={ref} className="plotly-chart" style={{ height }} />
    </div>
  )
}
