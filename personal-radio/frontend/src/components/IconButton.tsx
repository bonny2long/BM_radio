import type { ReactNode } from 'react'

export default function IconButton({
  label,
  onClick,
  children,
  active = false,
  disabled = false,
  size = 42,
  variant = 'default',
}: {
  label: string
  onClick?: () => void
  children: ReactNode
  active?: boolean
  disabled?: boolean
  size?: number
  variant?: 'default' | 'ghost'
}) {
  const handlePressStart = (el: HTMLButtonElement) => {
    if (!disabled) el.style.transform = 'scale(0.88)'
  }
  const handlePressEnd = (el: HTMLButtonElement) => {
    el.style.transform = 'scale(1)'
  }

  return (
    <button
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      onMouseDown={e => handlePressStart(e.currentTarget)}
      onMouseUp={e => handlePressEnd(e.currentTarget)}
      onMouseLeave={e => handlePressEnd(e.currentTarget)}
      onTouchStart={e => handlePressStart(e.currentTarget)}
      onTouchEnd={e => handlePressEnd(e.currentTarget)}
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        display: 'grid',
        placeItems: 'center',
        background: active
          ? 'var(--accent-primary)'
          : variant === 'ghost'
          ? 'transparent'
          : 'var(--bg-surface)',
        color: active ? '#fff' : 'var(--text-primary)',
        border: active || variant === 'ghost' ? 'none' : '1px solid var(--border-subtle)',
        opacity: disabled ? 0.38 : 1,
        boxShadow: active ? '0 4px 20px var(--accent-primary-glow)' : 'none',
        cursor: disabled ? 'not-allowed' : 'pointer',
        flexShrink: 0,
        transition: 'transform 0.1s ease, opacity 0.1s ease',
      }}
    >
      {children}
    </button>
  )
}

