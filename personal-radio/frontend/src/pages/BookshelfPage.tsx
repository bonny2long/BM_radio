import React from 'react';

const BookshelfPage: React.FC = () => {
  return (
    <div>
      <h1 style={{ marginBottom: '24px' }}>Bookshelf</h1>
      
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '32px' }}>
        <div style={{ background: 'var(--bg-card)', padding: '12px', borderRadius: 'var(--radius-s)', textAlign: 'center' }}>
          <div style={{ fontSize: '20px', fontWeight: 700 }}>0</div>
          <div style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>AVAILABLE</div>
        </div>
        <div style={{ background: 'var(--bg-card)', padding: '12px', borderRadius: 'var(--radius-s)', textAlign: 'center' }}>
          <div style={{ fontSize: '20px', fontWeight: 700 }}>0</div>
          <div style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>STARTED</div>
        </div>
        <div style={{ background: 'var(--bg-card)', padding: '12px', borderRadius: 'var(--radius-s)', textAlign: 'center' }}>
          <div style={{ fontSize: '20px', fontWeight: 700 }}>0</div>
          <div style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>FINISHED</div>
        </div>
      </div>

      <h2 style={{ fontSize: '18px', marginBottom: '16px' }}>Continue Listening</h2>
      <p style={{ color: 'var(--text-muted)' }}>No books in progress.</p>
    </div>
  );
};

export default BookshelfPage;
