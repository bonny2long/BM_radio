export default function PageError({
  message,
  onRetry,
}: {
  message: string
  onRetry: () => void
}) {
  return (
    <div
      className="card-premium"
      style={{ padding: 28, textAlign: 'center', marginTop: 12 }}
    >
      <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 16 }}>
        {message}
      </p>
      <button
        onClick={onRetry}
        style={{
          padding: '10px 20px',
          borderRadius: 'var(--radius-pill)',
          background: 'var(--accent-primary)',
          color: '#fff',
          fontWeight: 700,
          fontSize: 13,
        }}
      >
        Try again
      </button>
    </div>
  )
}
