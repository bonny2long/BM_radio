import React from 'react';

interface BottomNavProps {
  currentPage: string;
  onPageChange: (page: string) => void;
}

// Inline SVG icons — no dependency needed
const icons = {
  home: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 9.5L12 3l9 6.5V20a1 1 0 01-1 1H4a1 1 0 01-1-1V9.5z"/>
      <path d="M9 21V12h6v9"/>
    </svg>
  ),
  radio: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="14" r="8"/>
      <circle cx="12" cy="14" r="3"/>
      <path d="M6.343 6.343L4.22 4.22M17.657 6.343l2.122-2.122M12 2v3"/>
    </svg>
  ),
  library: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 18V5l12-2v13"/>
      <circle cx="6" cy="18" r="3"/>
      <circle cx="18" cy="16" r="3"/>
    </svg>
  ),
  bookshelf: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2zM22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/>
    </svg>
  ),
};

const navItems = [
  { label: 'Home', id: 'home' },
  { label: 'Radio', id: 'radio' },
  { label: 'Library', id: 'library' },
  { label: 'Books', id: 'bookshelf' },
] as const;

const BottomNav: React.FC<BottomNavProps> = ({ currentPage, onPageChange }) => {
  return (
    <nav style={{
      display: 'flex',
      justifyContent: 'space-around',
      alignItems: 'center',
      height: '72px',
      background: 'var(--bg-nav)',
      backdropFilter: 'blur(24px) saturate(1.6)',
      WebkitBackdropFilter: 'blur(24px) saturate(1.6)',
      borderTop: '1px solid var(--border-subtle)',
      paddingBottom: 'env(safe-area-inset-bottom)',
      paddingLeft: '8px',
      paddingRight: '8px',
    }}>
      {navItems.map((item) => {
        const isActive = currentPage === item.id;
        return (
          <button
            key={item.id}
            onClick={() => onPageChange(item.id)}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '5px',
              flex: 1,
              padding: '8px 4px',
              color: isActive ? 'var(--accent-primary)' : 'var(--text-muted)',
              transition: 'color var(--transition-fast)',
              position: 'relative',
            }}
          >
            {/* Active glow dot */}
            {isActive && (
              <span style={{
                position: 'absolute',
                top: '2px',
                left: '50%',
                transform: 'translateX(-50%)',
                width: '4px',
                height: '4px',
                borderRadius: '50%',
                background: 'var(--accent-primary)',
                boxShadow: '0 0 8px var(--accent-primary)',
              }} />
            )}
            <span style={{
              filter: isActive ? 'drop-shadow(0 0 6px var(--accent-primary))' : 'none',
              transition: 'filter var(--transition-base)',
            }}>
              {icons[item.id as keyof typeof icons]}
            </span>
            <span style={{
              fontSize: '10px',
              fontWeight: isActive ? 600 : 400,
              letterSpacing: isActive ? '0.02em' : '0',
            }}>
              {item.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
};

export default BottomNav;
