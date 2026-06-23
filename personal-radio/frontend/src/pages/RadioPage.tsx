import React from 'react';

const RadioPage: React.FC = () => {
  const stations: any[] = [];

  return (
    <div>
      <h1 style={{ marginBottom: '24px' }}>Radio Stations</h1>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {stations.length > 0 ? stations.map(station => (
          <div key={station.name} style={{
            background: 'var(--bg-card)',
            borderRadius: 'var(--radius-m)',
            padding: '16px',
            display: 'flex',
            alignItems: 'center',
            gap: '16px',
            borderLeft: `4px solid ${station.color}`
          }}>
            <div style={{
              width: '48px',
              height: '48px',
              borderRadius: 'var(--radius-s)',
              background: station.color,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '24px'
            }}>📻</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{station.name}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{station.type} Station</div>
            </div>
            <button style={{ fontSize: '24px' }}>▶️</button>
          </div>
        )) : (
          <p style={{ color: 'var(--text-muted)' }}>No stations available. Try scanning your library.</p>
        )}
      </div>
    </div>
  );
};

export default RadioPage;
