import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  Home, FileSpreadsheet, Layers, ScanSearch, Building2, Users, LogOut, ChevronRight,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { cn } from '../lib/cn'
import logoPreta from '../assets/logo-preta.svg'

const NAV = [
  { section: null, items: [{ label: 'Início', to: '/', icon: Home, end: true }] },
  {
    section: 'Ferramentas',
    items: [
      { label: 'Conciliação RGF', to: '/conciliacao/rgf', icon: FileSpreadsheet },
      { label: 'Conciliação RREO', to: '/conciliacao/rreo', icon: Layers },
      { label: 'Auditoria RIT', to: '/auditoria', icon: ScanSearch },
    ],
  },
  {
    section: 'Cadastros',
    items: [
      { label: 'Municípios', to: '/municipios', icon: Building2 },
      { label: 'Usuários', to: '/usuarios', icon: Users, adminOnly: true },
    ],
  },
]

function NavItem({ item, onNavigate }) {
  const { icon: Icon } = item
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13.5px] font-medium tracking-tight',
          'transition-all duration-300 ease-expo',
          isActive
            ? 'bg-gold-wash text-gold-deep shadow-[inset_0_0_0_1px_rgba(156,122,22,0.14)]'
            : 'text-stone-500 hover:bg-stone-100 hover:text-ink',
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon
            size={17}
            strokeWidth={isActive ? 2 : 1.6}
            className={cn('shrink-0 transition-colors', isActive ? 'text-gold' : 'text-stone-400 group-hover:text-stone-600')}
          />
          <span className="flex-1">{item.label}</span>
          {isActive && <ChevronRight size={14} className="text-gold/60" />}
        </>
      )}
    </NavLink>
  )
}

function SidebarInner({ onNavigate }) {
  const { user, logout, isAdmin } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-full flex-col">
      {/* Brand */}
      <div className="px-5 pb-5 pt-6">
        <img src={logoPreta} alt="Kora" className="h-6 w-auto" />
        <p className="mt-2.5 text-[11px] font-medium uppercase tracking-eyebrow text-stone-400">
          Auditoria Municipal
        </p>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-6 overflow-y-auto px-3 pb-4">
        {NAV.map((group, gi) => {
          const items = group.items.filter((it) => !it.adminOnly || isAdmin)
          if (items.length === 0) return null
          return (
            <div key={gi}>
              {group.section && (
                <p className="mb-1.5 px-3 text-[10.5px] font-semibold uppercase tracking-eyebrow text-stone-400">
                  {group.section}
                </p>
              )}
              <div className="space-y-0.5">
                {items.map((item) => (
                  <NavItem key={item.to} item={item} onNavigate={onNavigate} />
                ))}
              </div>
            </div>
          )
        })}
      </nav>

      {/* User footer */}
      <div className="mx-3 mb-3 flex items-center gap-3 rounded-2xl border border-stone-200/70 bg-stone-50 p-2.5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ink text-[13px] font-semibold text-white">
          {user?.nome?.[0]?.toUpperCase() || 'U'}
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-[13px] font-semibold tracking-tight text-ink">{user?.nome}</span>
          <span className="truncate text-[11.5px] text-stone-400">
            {user?.role === 'admin' ? 'Administrador' : 'Auditor'}
          </span>
        </div>
        <button
          onClick={handleLogout}
          title="Sair"
          className="flex h-8 w-8 items-center justify-center rounded-full text-stone-400 transition-all duration-200 hover:bg-white hover:text-danger"
        >
          <LogOut size={15} strokeWidth={1.75} />
        </button>
      </div>
    </div>
  )
}

// Hamburger that morphs into an X
function MorphMenu({ open, onClick }) {
  return (
    <button
      onClick={onClick}
      aria-label="Menu"
      className="relative flex h-10 w-10 items-center justify-center rounded-full border border-stone-200 bg-surface shadow-soft lg:hidden"
    >
      <span className="relative block h-4 w-5">
        <span
          className={cn(
            'absolute left-0 h-[1.6px] w-5 rounded-full bg-ink transition-all duration-400 ease-expo',
            open ? 'top-1/2 -translate-y-1/2 rotate-45' : 'top-0.5',
          )}
        />
        <span
          className={cn(
            'absolute left-0 top-1/2 h-[1.6px] w-5 -translate-y-1/2 rounded-full bg-ink transition-all duration-300 ease-expo',
            open ? 'opacity-0' : 'opacity-100',
          )}
        />
        <span
          className={cn(
            'absolute left-0 h-[1.6px] w-5 rounded-full bg-ink transition-all duration-400 ease-expo',
            open ? 'top-1/2 -translate-y-1/2 -rotate-45' : 'bottom-0.5',
          )}
        />
      </span>
    </button>
  )
}

export default function AppShell({ children }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="flex min-h-[100dvh]">
      {/* Desktop rail */}
      <aside className="sticky top-0 hidden h-[100dvh] w-[264px] shrink-0 p-3 lg:block">
        <div className="h-full rounded-3xl border border-stone-200/70 bg-surface shadow-card">
          <SidebarInner />
        </div>
      </aside>

      {/* Mobile drawer */}
      <div
        className={cn(
          'fixed inset-0 z-40 lg:hidden',
          open ? 'pointer-events-auto' : 'pointer-events-none',
        )}
      >
        <div
          onClick={() => setOpen(false)}
          className={cn(
            'absolute inset-0 bg-ink/25 backdrop-blur-sm transition-opacity duration-400 ease-expo',
            open ? 'opacity-100' : 'opacity-0',
          )}
        />
        <div
          className={cn(
            'absolute left-0 top-0 h-full w-[280px] max-w-[85vw] p-3 transition-transform duration-500 ease-glide',
            open ? 'translate-x-0' : '-translate-x-[110%]',
          )}
        >
          <div className="h-full rounded-3xl border border-stone-200/70 bg-surface shadow-float">
            <SidebarInner onNavigate={() => setOpen(false)} />
          </div>
        </div>
      </div>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <div className="sticky top-0 z-30 flex items-center gap-3 border-b border-stone-200/60 bg-canvas/85 px-4 py-3 backdrop-blur-md lg:hidden">
          <MorphMenu open={open} onClick={() => setOpen((o) => !o)} />
          <img src={logoPreta} alt="Kora" className="h-5 w-auto" />
        </div>

        <main className="flex-1 px-5 py-8 sm:px-8 lg:px-10 lg:py-12">
          <div className="mx-auto w-full max-w-content">{children}</div>
        </main>

        <footer className="flex flex-col items-center justify-between gap-1 px-6 py-6 text-[11.5px] text-stone-400 sm:flex-row sm:px-10">
          <span>Kora · Plataforma de Auditoria Contábil Municipal</span>
          <span className="font-mono">© {new Date().getFullYear()}</span>
        </footer>
      </div>
    </div>
  )
}
