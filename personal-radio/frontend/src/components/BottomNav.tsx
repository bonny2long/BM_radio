import React from 'react';

interface BottomNavProps {
  currentPage: string;
  onPageChange: (page: string) => void;
}

const BottomNav: React.FC<BottomNavProps> = ({ currentPage, onPageChange }) => {
  const navItems = [
    { label: 'Home', icon: '🏠', id: 'home' },
    { label: 'Radio', icon: '📻', id: 'radio' },
    { label: 'Library', icon: '🎵', id: 'library' },
    { label: 'Books', icon: '📚', id: 'bookshelf' },
  ];

  return (
    <nav style={{
      display: 'flex',
      justifyContent: 'space-around',
      alignItems: 'center',
      height: '70px',
      background: 'var(--bg-nav)',
      backdropFilter: 'blur(10px)',
      borderTop: '1px solid rgba(255, 255, 255, 0.1)',
      paddingBottom: 'env(safe-area-inset-bottom)'
    }}>
      {navItems.map((item) => (
        <button 
          key={item.id} 
          onClick={() => onPageChange(item.id)}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '4px',
            color: currentPage === item.id ? 'var(--accent-primary)' : 'var(--text-secondary)',
            fontSize: '12px',
            transition: 'color 0.2s'
          }}
        >
          <span style={{ fontSize: '24px' }}>{item.icon}</span>
          <span style={{ fontWeight: currentPage === item.id ? 600 : 400 }}>{item.label}</span>
        </button>
      ))}
    </nav>
  );
};

export default BottomNav;
