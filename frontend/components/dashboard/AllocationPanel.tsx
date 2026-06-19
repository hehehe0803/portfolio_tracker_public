'use client'

import { useMemo, useState } from 'react'
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'

// Grayscale palette for donut slices — warm tones, no neon
const SLICE_COLORS: string[] = [
  '#e8e3d4', '#c8c2b1', '#a5a094', '#7f7b72',
  '#5d5a54', '#3e3c38', '#2c2b28',
]

const RADIAN = Math.PI / 180
const CHART_SIZE = 154
const CHART_CENTER = CHART_SIZE / 2
const CALLOUT_TOP = 8

function getSliceColor(index: number): string {
  return SLICE_COLORS[index % SLICE_COLORS.length]
}

function fmtUsd(n: number, dec = 0) {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD',
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  }).format(n)
}

function titleCase(value: string) {
  return value.replace(/[_-]/g, ' ').replace(/\b\w/g, char => char.toUpperCase())
}

interface AllocationPanelProps {
  byAssetType: Record<string, number>
}

export function AllocationPanel({ byAssetType }: AllocationPanelProps) {
  const entries = Object.entries(byAssetType).filter(([, v]) => v > 0)
  const total = entries.reduce((s, [, v]) => s + v, 0)
  const pieData = useMemo(() => entries.map(([type, value], index) => ({
    name: type,
    label: titleCase(type),
    value: Math.round(value * 100) / 100,
    rawValue: value,
    percent: total > 0 ? (value / total) * 100 : 0,
    color: getSliceColor(index),
  })), [entries, total])
  const [selectedIndex, setSelectedIndex] = useState(0)
  const selected = pieData[selectedIndex] ?? pieData[0]

  let calloutGeometry = null
  if (selected && total > 0) {
    const previousValue = pieData.slice(0, selectedIndex).reduce((sum, item) => sum + item.rawValue, 0)
    const midpoint = ((previousValue + selected.rawValue / 2) / total) * 360 - 90
    const anchorRadius = 62
    const elbowRadius = 76
    const anchorX = CHART_CENTER + anchorRadius * Math.cos(midpoint * RADIAN)
    const anchorY = CHART_CENTER + anchorRadius * Math.sin(midpoint * RADIAN)
    const elbowX = CHART_CENTER + elbowRadius * Math.cos(midpoint * RADIAN)
    const elbowY = CHART_CENTER + elbowRadius * Math.sin(midpoint * RADIAN)
    const calloutX = CHART_SIZE + 18
    const calloutY = CALLOUT_TOP
    const lineEndX = CHART_SIZE + 18
    const lineEndY = calloutY + 44
    calloutGeometry = { anchorX, anchorY, elbowX, elbowY, lineEndX, lineEndY, calloutX, calloutY }
  }

  return (
    <section className="panel panel-padded allocation-panel" aria-labelledby="allocation-heading">
      <div className="panel-toolbar">
        <span id="allocation-heading" className="panel-header">Allocation</span>
        <span className="panel-kicker">{entries.length} types</span>
      </div>

      {entries.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--fg-3)' }}>No allocation data yet.</p>
      ) : (
        <>
          <div className="allocation-stage" aria-live="polite">
            <div className="allocation-chart-wrap">
              <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={43}
                    outerRadius={62}
                    paddingAngle={1.2}
                    strokeWidth={0}
                    onClick={(_, index) => setSelectedIndex(index)}
                    onMouseEnter={(_, index) => setSelectedIndex(index)}
                  >
                    {pieData.map((item, i) => (
                      <Cell
                        key={item.name}
                        fill={item.color}
                        className="allocation-slice"
                        opacity={i === selectedIndex ? 1 : 0.58}
                        stroke={i === selectedIndex ? 'var(--fg-0)' : 'transparent'}
                        strokeWidth={i === selectedIndex ? 1.5 : 0}
                        cursor="pointer"
                      />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="allocation-total" aria-hidden="true">
                <span>Total</span>
                <strong>{fmtUsd(total)}</strong>
              </div>
            </div>

            {selected && calloutGeometry ? (
              <div className="allocation-callout-layer" aria-hidden="true">
                <svg className="allocation-leader" viewBox={`-210 0 ${CHART_SIZE + 420} ${CHART_SIZE}`} preserveAspectRatio="none">
                  <circle
                    className="allocation-leader-dot"
                    cx={calloutGeometry.anchorX}
                    cy={calloutGeometry.anchorY}
                    r="3"
                    fill={selected.color}
                  />
                  <polyline
                    className="allocation-leader-line"
                    points={`${calloutGeometry.anchorX},${calloutGeometry.anchorY} ${calloutGeometry.elbowX},${calloutGeometry.elbowY} ${calloutGeometry.lineEndX},${calloutGeometry.lineEndY}`}
                    stroke={selected.color}
                  />
                </svg>
                <div
                  key={selected.name}
                  data-testid="allocation-callout"
                  className="allocation-callout"
                  style={{
                    left: calloutGeometry.calloutX,
                    top: calloutGeometry.calloutY,
                    borderColor: `${selected.color}55`,
                    ['--callout-color' as string]: selected.color,
                  }}
                >
                  <span>{selected.label}</span>
                  <strong>{fmtUsd(selected.rawValue)}</strong>
                  <em>{selected.percent.toFixed(1)}% of portfolio</em>
                </div>
              </div>
            ) : null}
          </div>

          <div className="allocation-list" aria-label="Allocation categories">
            {pieData.map((item, i) => (
              <button
                key={item.name}
                type="button"
                className="allocation-row"
                data-active={i === selectedIndex}
                aria-pressed={i === selectedIndex}
                aria-label={`${item.label}: ${fmtUsd(item.rawValue)}, ${item.percent.toFixed(1)} percent`}
                onClick={() => setSelectedIndex(i)}
                onFocus={() => setSelectedIndex(i)}
              >
                <span className="allocation-dot" style={{ background: item.color }} />
                <span className="allocation-name">{item.label}</span>
                <span className="allocation-value">{fmtUsd(item.rawValue)}</span>
                <span className="allocation-pct">{item.percent.toFixed(0)}%</span>
                <span className="allocation-bar" aria-hidden="true">
                  <span style={{ width: `${item.percent}%`, background: item.color }} />
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  )
}
