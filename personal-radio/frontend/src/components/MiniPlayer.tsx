import React from 'react';

const PauseIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
    <rect x="6" y="4" width="4" height="16" rx="1"/>
    <rect x="14" y="4" width="4" height="16" rx="1"/>
  </svg>
);

const PlayIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
    <polygon points="5,3 19,12 5,21"/>
  </svg>
);

const NextIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
    <polygon points="5,5 15,12 5,19"/>
    <rect x="17" y="5" width="2" height="14" rx="1"/>
  </svg>
);

// Animated waveform bars
const WaveformBars: React.FC<{ playing: boolean }> = ({ playing }) => (
  <span style={{ display: 'flex', alignItems: 'center', gap: '2px', height: '16px' }}>
    {[0.6, 1.0, 0.7, 0.9, 0.5].map((h, i) => (
      <span
        key={i}
        style={{
          display: 'inline-block',
          width: '3px',
          height: `${h * 16}px`,
          background: 'var(--accent-primary)',
          borderRadius: '2px',
          opacity: playing ? 1 : 0.3,
          animation: playing ? `waveBar${i} 0.8s ease-in-out infinite alternate` : 'none',
          animationDelay: `${i * 0.12}s`,
        }}
      />
    ))}
    <style>{`
      @keyframes waveBar0 { from { height: 6px } to { height: 14px } }
      @keyframes waveBar1 { from { height: 10px } to { height: 4px } }
      @keyframes waveBar2 { from { height: 8px } to { height: 16px } }
      @keyframes waveBar3 { from { height: 14px } to { height: 6px } }
      @keyframes waveBar4 { from { height: 5px } to { height: 12px } }
    `}</style>
  </span>
);

const MiniPlayer: React.FC = () => {
  // Placeholder state — wire to real playback state when backend is connected
  const isPlaying = false;
  const trackTitle = 'Not Playing';
  const trackSub = 'No track selected';

  return (
    <div style={{
      margin: '0 10px 8px',
      borderRadius: 'var(--radius-l)',
      background: 'rgba(18, 18, 28, 0.95)',
      backdropFilter: 'blur(30px) saturate(1.8)',
      WebkitBackdropFilter: 'blur(30px) saturate(1.8)',
      border: '1px solid var(--border-subtle)',
      boxShadow: '0 -2px 40px rgba(124, 111, 255, 0.1), 0 4px 30px rgba(0,0,0,0.6)',
      display: 'flex',
      alignItems: 'center',
      padding: '10px 14px',
      gap: '12px',
    }}>
      {/* Album art */}
      <div style={{
        width: '44px',
        height: '44px',
        flexShrink: 0,
        borderRadius: 'var(--radius-s)',
        background: 'var(--gradient-radio)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        boxShadow: '0 4px 12px rgba(124,111,255,0.4)',
        position: 'relative',
        overflow: 'hidden',
      }}>
        {/* Vinyl record suggestion */}
        <div style={{
          position: 'absolute',
          width: '24px',
          height: '24px',
          borderRadius: '50%',
          border: '1px solid rgba(255,255,255,0.15)',
          background: 'rgba(0,0,0,0.3)',
        }}>
          <div style={{
            position: 'absolute',
            top: '50%', left: '50%',
            transform: 'translate(-50%, -50%)',
            width: '6px', height: '6px',
            borderRadius: '50%',
            background: 'rgba(255,255,255,0.5)',
          }} />
        </div>
      </div>

      {/* Track info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ 
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          marginBottom: '2px',
        }}>
          <span style={{ 
            fontSize: '14px', 
            fontWeight: 600,
            whiteSpace: 'nowrap', 
            overflow: 'hidden', 
            textOverflow: 'ellipsis',
            color: 'var(--text-primary)',
          }}>
            {trackTitle}
          </span>
          <WaveformBars playing={isPlaying} />
        </div>
        <div style={{ 
          fontSize: '11px', 
          color: 'var(--text-secondary)',
          whiteSpace: 'nowrap', 
          overflow: 'hidden', 
          textOverflow: 'ellipsis',
          fontWeight: 400,
        }}>
          {trackSub}
        </div>
      </div>

      {/* Controls */}
      <div style={{ 
        display: 'flex', 
        alignItems: 'center',
        gap: '4px',
        flexShrink: 0,
      }}>
        <button
          style={{
            width: '40px',
            height: '40px',
            borderRadius: '50%',
            background: 'var(--accent-primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            boxShadow: '0 2px 12px var(--accent-primary-glow)',
            transition: 'transform var(--transition-fast), box-shadow var(--transition-fast)',
          }}
          onMouseDown={e => (e.currentTarget.style.transform = 'scale(0.92)')}
          onMouseUp={e => (e.currentTarget.style.transform = 'scale(1)')}
        >
          {isPlaying ? <PauseIcon /> : <PlayIcon />}
        </button>
        <button
          style={{
            width: '36px',
            height: '36px',
            borderRadius: '50%',
            background: 'var(--bg-surface)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-secondary)',
            border: '1px solid var(--border-subtle)',
            transition: 'color var(--transition-fast)',
          }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--text-primary)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-secondary)')}
        >
          <NextIcon />
        </button>
      </div>
    </div>
  );
};

export default MiniPlayer;
