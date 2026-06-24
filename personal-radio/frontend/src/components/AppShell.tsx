import React from 'react';
import BottomNav from './BottomNav';
import MiniPlayer from './MiniPlayer';

interface AppShellProps {
  children: React.ReactNode;
  currentPage: string;
  onPageChange: (page: string) => void;
}

const AppShell: React.FC<AppShellProps> = ({ children, currentPage, onPageChange }) => {
  return (
    <div style={{ 
      display: 'flex', 
      flexDirection: 'column', 
      minHeight: '100vh',
      paddingBottom: '152px',
      maxWidth: '600px',
      margin: '0 auto',
      width: '100%',
    }}>
      <main style={{ 
        flex: 1, 
        padding: '24px 20px 0',
      }}>
        {children}
      </main>
      
      <div style={{ 
        position: 'fixed', 
        bottom: 0, 
        left: '50%',
        transform: 'translateX(-50%)',
        width: '100%',
        maxWidth: '600px',
        zIndex: 100,
        display: 'flex',
        flexDirection: 'column',
      }}>
        <MiniPlayer />
        <BottomNav currentPage={currentPage} onPageChange={onPageChange} />
      </div>
    </div>
  );
};

export default AppShell;
