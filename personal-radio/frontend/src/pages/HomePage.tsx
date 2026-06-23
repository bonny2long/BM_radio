import React from 'react';

const HomePage: React.FC = () => {
  return (
    <div>
      <h1 style={{ marginBottom: '24px' }}>BM Radio</h1>
      
      <section style={{ marginBottom: '32px' }}>
        <h2 style={{ fontSize: '18px', marginBottom: '16px', color: 'var(--text-secondary)' }}>Quick Start</h2>
        <div style={{
          height: '160px',
          background: 'var(--gradient-radio)',
          borderRadius: 'var(--radius-l)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'flex-end',
          padding: '20px',
          opacity: 0.5
        }}>
          <h3 style={{ fontSize: '24px' }}>No Favorites Yet</h3>
          <p style={{ opacity: 0.8 }}>Add some tracks to start your radio.</p>
        </div>
      </section>

      <section>
        <h2 style={{ fontSize: '18px', marginBottom: '16px', color: 'var(--text-secondary)' }}>Recently Added</h2>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <p style={{ color: 'var(--text-muted)', gridColumn: 'span 2' }}>No media added yet.</p>
        </div>
      </section>
    </div>
  );
};

export default HomePage;
