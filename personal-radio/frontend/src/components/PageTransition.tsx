import type { ReactNode } from 'react'

export default function PageTransition({ pageKey, children }: { pageKey: string; children: ReactNode }) {
  return (
    <div className="page-transition" data-page-key={pageKey}>
      {children}
    </div>
  )
}
