import React from 'react';

const HomePage: React.FC = () => {
  const timeOfDay = (() => {
    const h = new Date().getHours();
    if (h < 12) return 'Morning';
    if (h < 18) return 'Afternoon';
    return 'Evening';
  })();

  return (
    <div style={{ paddingBottom: '16px' }}>
      {/* Header */}
      <div style={{ marginBottom: '28px' }}>
        <p style={{ 
          fontSize: '12px', 
          fontWeight: 600, 
          letterSpacing: '0.1em', 
          textTransform: 'uppercase',
          color: 'var(--text-muted)',
          marginBottom: '4px',
        }}>
          Good {timeOfDay}
        </p>
        <h1 style={{ 
          fontSize: '2rem', 
          fontWeight: 800, 
          letterSpacing: '-0.03em',
          background: 'linear-gradient(135deg, var(--text-primary) 0%, var(--text-secondary) 100%)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          backgroundClip: 'text',
        }}>
          BM Radio
        </h1>
      </div>

      {/* Quick Start hero */}
      <section style={{ marginBottom: '32px' }}>
        <p className="section-label">Quick Start</p>
        <div style={{
          borderRadius: 'var(--radius-l)',
          background: 'var(--gradient-radio)',
          padding: '28px 24px',
          position: 'relative',
          overflow: 'hidden',
          minHeight: '140px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'flex-end',
          boxShadow: '0 8px 32px rgba(124,111,255,0.3)',
        }}>
          {/* Decorative rings */}
          <div style={{
            position: 'absolute',
            top: '-40px',
            right: '-40px',
            width: '160px',
            height: '160px',
            borderRadius: '50%',
            border: '1px solid rgba(255,255,255,0.08)',
          }} />
          <div style={{
            position: 'absolute',
            top: '-20px',
            right: '-20px',
            width: '100px',
            height: '100px',
            borderRadius: '50%',
            border: '1px solid rgba(255,255,255,0.12)',
          }} />

          <h3 style={{ 
            fontSize: '20px', 
            fontWeight: 700,
            color: '#fff',
            marginBottom: '6px',
          }}>
            No Favorites Yet
          </h3>
          <p style={{ 
            fontSize: '13px',
            color: 'rgba(255,255,255,0.72)',
            fontWeight: 400,
          }}>
            Mark tracks as favorites to start here.
          </p>
        </div>
      </section>

      {/* Recently Added */}
      <section>
        <p className="section-label">Recently Added</p>
        <div style={{
          borderRadius: 'var(--radius-m)',
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
          padding: '24px',
          textAlign: 'center',
          boxShadow: 'var(--shadow-card)',
        }}>
          {/* Placeholder vinyl icon */}
          <div style={{
            width: '48px',
            height: '48px',
            borderRadius: '50%',
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            margin: '0 auto 12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>
            </svg>
          </div>
          <p style={{ fontSize: '14px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '4px' }}>
            No media scanned yet
          </p>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Point your library at a folder and scan to begin.
          </p>
        </div>
      </section>
    </div>
  );
};

export default HomePage;
