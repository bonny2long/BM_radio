import React from 'react'
import BottomNav from './BottomNav'
import MiniPlayer from './MiniPlayer'
export default function AppShell({children,currentPage,onPageChange,onOpenNowPlaying}:{children:React.ReactNode;currentPage:string;onPageChange:(page:string)=>void;onOpenNowPlaying:()=>void}){const showNav=currentPage!=='nowPlaying';return <div className="app-shell" data-page={currentPage}><main className="app-main">{children}</main>{showNav&&<div className="bottom-rail"><MiniPlayer onOpen={onOpenNowPlaying}/><BottomNav currentPage={currentPage} onPageChange={onPageChange}/></div>}</div>}
