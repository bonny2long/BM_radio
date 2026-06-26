import { useRef } from 'react'

export default function useLongPress(onLongPress: () => void, threshold = 500) {
  const timer = useRef<number | null>(null)
  const start = useRef<{ x: number; y: number } | null>(null)
  const fired = useRef(false)

  const clear = () => {
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
    start.current = null
    window.setTimeout(() => { fired.current = false }, 0)
  }

  return {
    onPointerDown: (event: React.PointerEvent) => {
      if (event.pointerType === 'mouse' && event.button !== 0) return
      fired.current = false
      start.current = { x: event.clientX, y: event.clientY }
      timer.current = window.setTimeout(() => {
        fired.current = true
        onLongPress()
      }, threshold)
    },
    onPointerMove: (event: React.PointerEvent) => {
      if (!start.current || timer.current === null) return
      const dx = Math.abs(event.clientX - start.current.x)
      const dy = Math.abs(event.clientY - start.current.y)
      if (dx > 10 || dy > 10) clear()
    },
    onPointerUp: clear,
    onPointerCancel: clear,
    onClickCapture: (event: React.MouseEvent) => {
      if (fired.current) {
        event.preventDefault()
        event.stopPropagation()
      }
    },
  }
}