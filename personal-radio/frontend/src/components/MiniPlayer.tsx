import React from 'react';

const MiniPlayer: React.FC = () => {
  return (
    <div style={{
      height: '64px',
      margin: '0 8px 8px 8px',
      borderRadius: 'var(--radius-m)',
      background: 'var(--bg-card)',
      display: 'flex',
      alignItems: 'center',
      padding: '0 12px',
      gap: '12px',
      boxShadow: 'var(--shadow)',
      border: '1px solid rgba(255, 255, 255, 0.05)'
    }}>
      <div style={{
        width: '40px',
        height: '40px',
        background: 'var(--gradient-radio)',
        borderRadius: 'var(--radius-s)'
      }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ 
          fontSize: '14px', 
          fontWeight: 600, 
          whiteSpace: 'nowrap', 
          overflow: 'hidden', 
          textOverflow: 'ellipsis' 
        }}>
          Not Playing
        </div>
        <div style={{ 
          fontSize: '12px', 
          color: 'var(--text-secondary)',
          whiteSpace: 'nowrap', 
          overflow: 'hidden', 
          textOverflow: 'ellipsis' 
        }}>
          No track selected
        </div>
      </div>
      <div style={{ display: 'flex', gap: '16px', fontSize: '20px' }}>
        <button>⏯️</button>
        <button>⏭️</button>
      </div>
    </div>
  );
};

export default MiniPlayer;
