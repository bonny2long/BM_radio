import type { ReactNode } from 'react'

type NavType = 'tab' | 'push' | 'pop'

export default function PageTransition({
  pageKey,
  navType = 'tab',
  children,
}: {
  pageKey: string
  navType?: NavType
  children: ReactNode
}) {
  return (
    <div
      className="page-transition"
      data-page-key={pageKey}
      data-nav-type={navType === 'tab' ? undefined : navType}
    >
      {children}
    </div>
  )
}
