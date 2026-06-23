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
      paddingBottom: '160px'
    }}>
      <main style={{ flex: 1, padding: '20px' }}>
        {children}
      </main>
      
      <div style={{ 
        position: 'fixed', 
        bottom: 0, 
        left: 0, 
        right: 0, 
        zIndex: 100,
        display: 'flex',
        flexDirection: 'column'
      }}>
        <MiniPlayer />
        <BottomNav currentPage={currentPage} onPageChange={onPageChange} />
      </div>
    </div>
  );
};

export default AppShell;
