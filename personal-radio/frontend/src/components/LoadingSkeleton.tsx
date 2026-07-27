type Props = {
  rows?: number
  compact?: boolean
  preserveSpace?: boolean
}

export default function LoadingSkeleton({ rows = 4, compact = false, preserveSpace = false }: Props) {
  const rowHeight = compact ? 48 : 72
  const gap = compact ? 8 : 10
  const minHeight = preserveSpace ? rows * (compact ? 56 : 82) : undefined

  return (
    <div style={{ display: 'grid', gap, minHeight }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            height: rowHeight,
            borderRadius: 'var(--radius-m)',
            background: 'var(--bg-card)',
            border: '1px solid var(--border-subtle)',
            overflow: 'hidden',
            position: 'relative',
          }}
        >
          <div
            style={{
              position: 'absolute',
              inset: 0,
              background:
                'linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.035) 50%, transparent 100%)',
              animation: 'shimmer 1.6s infinite',
              animationDelay: `${i * 0.1}s`,
            }}
          />
        </div>
      ))}
      <style>{`
        @keyframes shimmer {
          0%   { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
      `}</style>
    </div>
  )
}
