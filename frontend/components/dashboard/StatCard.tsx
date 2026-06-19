interface StatCardProps {
  label: string
  value: string
  sub?: string
  subColor?: 'pos' | 'neg' | 'muted'
  accent?: 'green' | 'amber' | 'blue' | 'dim' | 'red'
}

export function StatCard({ label, value, sub, subColor = 'muted', accent = 'dim' }: StatCardProps) {
  const subClass =
    subColor === 'pos' ? 'val-pos' : subColor === 'neg' ? 'val-neg' : 'val-muted'

  const accentColor =
    accent === 'green' ? 'var(--pl-up)'
    : accent === 'amber' ? 'var(--warn)'
    : accent === 'red' ? 'var(--pl-dn)'
    : accent === 'blue' ? 'var(--fg-1)'
    : 'var(--fg-3)'

  return (
    <div
      className="panel panel-bento"
      style={{
        padding: 20,
        borderTop: `2px solid ${accentColor}`,
        opacity: 1,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span className="stat-label">{label}</span>
        <span
          style={{
            width: 6,
            height: 6,
            background: accentColor,
            borderRadius: '50%',
            flexShrink: 0,
          }}
        />
      </div>
      <p className="stat-value" style={{ marginTop: 14 }}>{value}</p>
      {sub && (
        <p className={`metric-sub ${subClass}`} style={{ marginTop: 6 }}>{sub}</p>
      )}
    </div>
  )
}
