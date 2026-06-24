import React from 'react';

interface StatCardProps {
  value: number;
  label: string;
  accentColor?: string;
}

const StatCard: React.FC<StatCardProps> = ({ value, label, accentColor = 'var(--accent-books)' }) => (
  <div style={{
    background: 'var(--bg-card)',
    border: '1px solid var(--border-subtle)',
    borderRadius: 'var(--radius-m)',
    padding: '14px 12px',
    textAlign: 'center',
    boxShadow: 'var(--shadow-card)',
  }}>
    <div style={{ 
      fontSize: '28px', 
      fontWeight: 800, 
      color: value > 0 ? accentColor : 'var(--text-primary)',
      letterSpacing: '-0.04em',
      lineHeight: 1,
      marginBottom: '6px',
    }}>
      {value}
    </div>
    <div style={{ 
      fontSize: '9px', 
      fontWeight: 700, 
      letterSpacing: '0.1em', 
      textTransform: 'uppercase',
      color: 'var(--text-muted)',
    }}>
      {label}
    </div>
  </div>
);

const BookshelfPage: React.FC = () => {
  const stats = { available: 0, started: 0, finished: 0 };

  return (
    <div style={{ paddingBottom: '16px' }}>
      {/* Header */}
      <div style={{ 
        marginBottom: '24px',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
      }}>
        <div>
          <h1 style={{ 
            fontSize: '2rem', 
            fontWeight: 800, 
            letterSpacing: '-0.03em',
            marginBottom: '2px',
          }}>
            Bookshelf
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            Your audiobook collection
          </p>
        </div>
        {/* Future "add" button placeholder */}
        <div style={{
          width: '36px',
          height: '36px',
          borderRadius: '50%',
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-secondary)',
        }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
        </div>
      </div>

      {/* Stats row */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: '1fr 1fr 1fr', 
        gap: '10px', 
        marginBottom: '28px',
      }}>
        <StatCard value={stats.available} label="Available" />
        <StatCard value={stats.started} label="Started" accentColor="var(--accent-primary)" />
        <StatCard value={stats.finished} label="Finished" accentColor="#34d399" />
      </div>

      {/* Continue Listening */}
      <section>
        <p className="section-label">Continue Listening</p>
        <div style={{
          borderRadius: 'var(--radius-l)',
          background: 'var(--bg-card)',
          border: '1px dashed var(--border-subtle)',
          padding: '40px 24px',
          textAlign: 'center',
          boxShadow: 'var(--shadow-card)',
        }}>
          <div style={{
            width: '56px',
            height: '56px',
            borderRadius: '50%',
            background: 'var(--accent-books-dim)',
            border: '1px solid rgba(255,155,80,0.25)',
            margin: '0 auto 14px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent-books)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/>
              <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/>
            </svg>
          </div>
          <p style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '5px' }}>
            No books in progress
          </p>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
            Start an audiobook to see it here.
          </p>
        </div>
      </section>
    </div>
  );
};

export default BookshelfPage;
