import React from 'react';

interface Station {
  name: string;
  type: string;
  color: string;
  trackCount?: number;
}

const RadioPage: React.FC = () => {
  const stations: Station[] = [];
  // When populated, each station has: name, type, color, trackCount

  return (
    <div style={{ paddingBottom: '16px' }}>
      <div style={{ marginBottom: '28px' }}>
        <h1 style={{ 
          fontSize: '2rem', 
          fontWeight: 800, 
          letterSpacing: '-0.03em',
          marginBottom: '4px',
        }}>
          Stations
        </h1>
        <p style={{ fontSize: '13px', color: 'var(--text-muted)', fontWeight: 400 }}>
          Auto-generated from your library
        </p>
      </div>

      {stations.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {stations.map(station => (
            <div
              key={station.name}
              className="card-premium"
              style={{
                padding: '14px 16px',
                display: 'flex',
                alignItems: 'center',
                gap: '14px',
                cursor: 'pointer',
              }}
            >
              <div style={{
                width: '48px',
                height: '48px',
                borderRadius: 'var(--radius-m)',
                background: station.color,
                flexShrink: 0,
                boxShadow: `0 4px 16px ${station.color}55`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="2.5" strokeLinecap="round">
                  <circle cx="12" cy="14" r="8"/>
                  <circle cx="12" cy="14" r="3"/>
                  <path d="M6.343 6.343L4.22 4.22M17.657 6.343l2.122-2.122M12 2v3"/>
                </svg>
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: '15px', marginBottom: '2px' }}>
                  {station.name}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  {station.type} · {station.trackCount ?? 0} tracks
                </div>
              </div>
              <button style={{
                width: '36px',
                height: '36px',
                borderRadius: '50%',
                background: 'var(--accent-primary)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                flexShrink: 0,
                boxShadow: '0 2px 10px var(--accent-primary-glow)',
              }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                  <polygon points="6,4 20,12 6,20"/>
                </svg>
              </button>
            </div>
          ))}
        </div>
      ) : (
        /* Empty state */
        <div style={{
          borderRadius: 'var(--radius-l)',
          background: 'var(--bg-card)',
          border: '1px dashed var(--border-subtle)',
          padding: '48px 24px',
          textAlign: 'center',
          boxShadow: 'var(--shadow-card)',
        }}>
          <div style={{
            width: '64px',
            height: '64px',
            borderRadius: '50%',
            background: 'var(--accent-primary-dim)',
            border: '1px solid var(--border-accent)',
            margin: '0 auto 16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--accent-primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="14" r="8"/>
              <circle cx="12" cy="14" r="3"/>
              <path d="M6.343 6.343L4.22 4.22M17.657 6.343l2.122-2.122M12 2v3"/>
            </svg>
          </div>
          <p style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
            No stations yet
          </p>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
            Scan your music library to generate<br/>genre and artist stations automatically.
          </p>
        </div>
      )}
    </div>
  );
};

export default RadioPage;
