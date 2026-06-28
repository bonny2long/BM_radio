import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

type BottomSheetProps = {
  open: boolean
  title?: string
  children: ReactNode
  onClose: () => void
}

export default function BottomSheet({ open, title, children, onClose }: BottomSheetProps) {
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current()
    }
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [open])

  if (!open) return null

  return createPortal(
    <div className="bottom-sheet-backdrop" onClick={onClose} role="presentation">
      <section className="bottom-sheet" role="dialog" aria-modal="true" aria-label={title ?? 'Options'} onClick={event => event.stopPropagation()}>
        <div className="bottom-sheet-handle" />
        <div className="bottom-sheet-header">
          <h2>{title}</h2>
          <button onClick={onClose} aria-label="Close" className="bottom-sheet-close">Ã—</button>
        </div>
        <div className="bottom-sheet-body">{children}</div>
      </section>
    </div>,
    document.body,
  )
}
