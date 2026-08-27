import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, AlertCircle, ShieldCheck, ScanSearch, FileSpreadsheet } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { api } from '../lib/api'
import { cn } from '../lib/cn'
import { Spinner } from '../ui'
import logoBranca from '../assets/logo-branca.svg'
import logoPreta from '../assets/logo-preta.svg'

const HIGHLIGHTS = [
  { icon: FileSpreadsheet, label: 'Conciliação RGF & RREO', desc: 'MSC × SICONFI, célula a célula' },
  { icon: ScanSearch, label: 'Auditoria automatizada', desc: 'Anexos de balanço → relatório RIT' },
  { icon: ShieldCheck, label: 'Conformidade fiscal', desc: 'LRF, FUNDEB, saúde e educação' },
]

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await api.post('/auth/login', { email, senha })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'Erro ao autenticar')
      }
      const data = await res.json()
      login(data.access_token, { id: data.id, nome: data.nome, email: data.email, role: data.role })
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid min-h-[100dvh] lg:grid-cols-[1.05fr_1fr]">
      {/* ── Brand panel ── */}
      <div className="relative hidden overflow-hidden bg-ink lg:flex lg:flex-col">
        {/* ambient mesh */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'radial-gradient(40rem 30rem at 20% 10%, rgba(156,122,22,0.4), transparent 60%), radial-gradient(36rem 30rem at 90% 90%, rgba(18,122,84,0.28), transparent 60%)',
          }}
        />
        <div className="pointer-events-none absolute inset-0 opacity-[0.04]"
          style={{ backgroundImage: 'radial-gradient(rgba(255,255,255,0.8) 1px, transparent 1px)', backgroundSize: '22px 22px' }}
        />

        <div className="relative flex h-full flex-col justify-between p-12 xl:p-16">
          <img src={logoBranca} alt="Kora" className="h-7 w-auto self-start" />

          <div className="max-w-md">
            <span className="mb-6 inline-flex items-center gap-2 rounded-pill border border-white/15 bg-white/5 px-3 py-1 font-mono text-[10.5px] font-medium uppercase tracking-eyebrow text-white/70">
              <span className="h-1.5 w-1.5 rounded-full bg-gold" />
              Plataforma de Auditoria
            </span>
            <h1 className="font-display text-[46px] font-semibold leading-[1.02] tracking-tightest text-white xl:text-[56px]">
              Contabilidade
              <br />
              <span className="text-white/45">municipal sob</span>
              <br />
              controle.
            </h1>
            <p className="mt-6 max-w-sm text-[15px] leading-relaxed text-white/55">
              Conciliação e auditoria contábil para prefeituras — do rascunho da MSC ao
              relatório de inspeção, num só lugar.
            </p>
          </div>

          <div className="flex flex-col gap-3">
            {HIGHLIGHTS.map((h) => (
              <div key={h.label} className="flex items-center gap-3.5">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-white/80">
                  <h.icon size={17} strokeWidth={1.6} />
                </span>
                <div>
                  <p className="text-[13.5px] font-semibold tracking-tight text-white">{h.label}</p>
                  <p className="text-[12px] text-white/45">{h.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Form panel ── */}
      <div className="flex items-center justify-center px-6 py-12 sm:px-10">
        <div className="w-full max-w-[400px] animate-reveal-up">
          {/* mobile logo */}
          <img src={logoPreta} alt="Kora" className="mb-10 h-6 w-auto lg:hidden" />

          <div className="mb-8">
            <span className="eyebrow mb-4">
              <span className="h-1.5 w-1.5 rounded-full bg-gold" />
              Acesso restrito
            </span>
            <h2 className="font-display text-[30px] font-semibold tracking-tighter text-ink">Entrar</h2>
            <p className="mt-1.5 text-[14px] text-stone-500">
              Use suas credenciais para acessar a plataforma.
            </p>
          </div>

          <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="text-[12.5px] font-semibold tracking-tight text-stone-600">E-mail</span>
              <input
                type="email"
                autoComplete="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="seu@email.com"
                className="h-12 w-full rounded-xl border border-stone-200 bg-surface px-4 text-sm text-ink shadow-soft transition-all duration-200 ease-expo placeholder:text-stone-400 hover:border-stone-300 focus:border-gold focus:shadow-focus focus:outline-none"
                required
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-[12.5px] font-semibold tracking-tight text-stone-600">Senha</span>
              <input
                type="password"
                autoComplete="current-password"
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                placeholder="••••••••"
                className="h-12 w-full rounded-xl border border-stone-200 bg-surface px-4 text-sm text-ink shadow-soft transition-all duration-200 ease-expo placeholder:text-stone-400 hover:border-stone-300 focus:border-gold focus:shadow-focus focus:outline-none"
                required
              />
            </label>

            {error && (
              <div className="flex items-center gap-2 rounded-xl border border-danger-ring bg-danger-bg px-3.5 py-2.5 text-[13px] font-medium text-danger animate-scale-in" role="alert">
                <AlertCircle size={15} className="shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !email || !senha}
              className={cn(
                'group mt-2 flex h-12 items-center justify-center gap-2 rounded-pill bg-gold pl-6 pr-2 font-semibold text-white',
                'shadow-[0_1px_2px_rgba(90,71,14,0.35),0_12px_28px_-10px_rgba(156,122,22,0.7)]',
                'transition-all duration-300 ease-expo hover:bg-gold-hover active:scale-[0.98]',
                'disabled:pointer-events-none disabled:opacity-45',
              )}
            >
              <span>{loading ? 'Verificando…' : 'Entrar no sistema'}</span>
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/15 transition-transform duration-300 ease-expo group-hover:translate-x-0.5 group-hover:scale-105">
                {loading ? <Spinner size={15} className="text-white" /> : <ArrowRight size={16} />}
              </span>
            </button>
          </form>

          <p className="mt-8 text-center text-[12px] text-stone-400">
            Kora · Auditoria Contábil Municipal
          </p>
        </div>
      </div>
    </div>
  )
}
