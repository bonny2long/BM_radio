
const Icon=({name}:{name:string})=><span style={{fontSize:18,lineHeight:1}}>{name}</span>
const items=[['Home','home','H'],['Radio','radio','R'],['Library','library','L'],['Books','bookshelf','B']] as const
export default function BottomNav({currentPage,onPageChange}:{currentPage:string;onPageChange:(page:string)=>void}){return <nav style={{width:'100%',boxSizing:'border-box',display:'flex',height:72,background:'var(--bg-nav)',backdropFilter:'blur(24px)',borderTop:'1px solid var(--border-subtle)',paddingBottom:'env(safe-area-inset-bottom)'}}>{items.map(([label,id,glyph])=>{const active=currentPage===id;return <button key={id} onClick={()=>onPageChange(id)} style={{flex:'1 1 0',minWidth:0,maxWidth:'25%',height:72,padding:'8px 0 10px',display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',gap:4,color:active?'var(--accent-primary)':'var(--text-muted)',position:'relative'}}><span style={{width:26,height:26,display:'grid',placeItems:'center',position:'relative'}}>{active&&<span className="nav-active-dot"/>}<Icon name={glyph}/></span><span style={{fontSize:10,fontWeight:active?600:400,whiteSpace:'nowrap'}}>{label}</span></button>})}</nav>}


