import { useEffect, useRef } from 'react'
import {
  CategoryScale, Chart, Filler, Legend, LinearScale, LineController, LineElement, PointElement, Tooltip,
} from 'chart.js'

Chart.register(CategoryScale, LinearScale, LineController, LineElement, PointElement, Tooltip, Legend, Filler)

// One style for every chart: validated categorical palette (fixed order, never cycled), recessive grid, 2px lines
export const SERIES_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']
const INK = '#52514e'
const GRID = '#e7e5e4'

// datasets: [{ label, data: [number|null], color, dashed?, points? }], labels: x axis texts
export default function LineChart({ labels, datasets, formatValue, height = 260, legend = datasets.length > 1 }) {
  const canvas = useRef(null)
  const chart = useRef(null)

  useEffect(() => {
    chart.current = new Chart(canvas.current, {
      type: 'line',
      data: {
        labels,
        datasets: datasets.map((d) => ({
          label: d.label, data: d.data, borderColor: d.color, backgroundColor: d.color,
          borderWidth: 2, borderDash: d.dashed ? [4, 4] : [], spanGaps: true, tension: 0,
          pointRadius: d.points ?? 0, pointHoverRadius: 5, pointBorderColor: '#fff', pointBorderWidth: 2,
        })),
      },
      options: {
        maintainAspectRatio: false, animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: legend, position: 'bottom', labels: { color: INK, boxWidth: 12, boxHeight: 2 } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${formatValue(c.parsed.y)}` } },
        },
        scales: {
          x: { ticks: { color: INK, maxTicksLimit: 7, maxRotation: 0 }, grid: { display: false } },
          y: { ticks: { color: INK, callback: formatValue, maxTicksLimit: 5 }, grid: { color: GRID }, border: { display: false } },
        },
      },
    })
    return () => chart.current.destroy()
  }, [labels, datasets, formatValue, legend])

  return <div style={{ height }}><canvas ref={canvas} /></div>
}
