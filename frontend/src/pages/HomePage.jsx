import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  FileSpreadsheet, Layers, ScanSearch, Building2, ArrowUpRight, ArrowRight,
  Plus, CheckCircle2, FileCheck2, Sparkles,
} from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../contexts/AuthContext'
import { useReveal } from '../hooks/useReveal'
import { cn } from '../lib/cn'
import { Eyebrow, Badge, Reveal, EmptyState, Spinner } from '../ui'

const TOOLS = [
  {
    to: '/conciliacao/rgf',
    icon: FileSpreadsheet,
    tag: 'RGF',
    title: 'Conciliação RGF',
    desc: 'Compara o rascunho da MSC com o arquivo homologado no SICONFI, célula a célula, e destaca as divergências por criticidade.',
  },
  {
    to: '/conciliacao/rreo',
    icon: Layers,
    tag: 'RREO',
    title: 'Conciliação RREO',
    desc: 'Confronta todos os anexos do RREO com o SICONFI e gera a planilha destacada mais o relatório de auditoria Kora.',
  },
]

export default function HomePage() {
  const { user, isAdmin } = useAuth()
  const [prefeituras, setPrefeituras] = useState([])
  const [loading, setLoading] = useState(true)
  const ref = useReveal([loading])

  useEffect(() => {
    api.get('/prefeituras?ativo=true')
      .then((r) => (r.ok ? r.json() : []))
      .then(setPrefeituras)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const firstName = user?.nome?.split(' ')[0] || 'auditor'
  const shown = prefeituras.slice(0, 6)

  return (
    <div ref={ref}>
      {/* ── Hero ── */}
      <Reveal className="mb-10">
        <Eyebrow className="mb-4">Plataforma unificada</Eyebrow>
        <h1 className="font-display text-[32px] font-semibold leading-[1.04] tracking-tighter text-ink sm:text-[42px]">
          Olá, {firstName}.
          <br />
          <span className="text-stone-400">O que vamos auditar hoje?</span>
        </h1>
        <p className="mt-4 max-w-xl text-[14.5px] leading-relaxed text-stone-500">
          Escolha uma ferramenta para começar ou acesse um município para ver o histórico.
        </p>
      </Reveal>

      {/* ── Ferramentas ── */}
      <div className="mb-4 flex items-center gap-2.5">
        <h2 className="font-display text-[13px] font-semibold uppercase tracking-eyebrow text-stone-400">Ferramentas</h2>
        <div className="h-px flex-1 bg-stone-200/70" />
      </div>

      {/* Flagship auditor card */}
      <Reveal delay={60}>
        <Link
          to="/auditoria"
          className="group relative mb-5 block overflow-hidden rounded-[1.75rem] border border-stone-200/70 bg-stone-100/50 p-1.5 shadow-card transition-all duration-500 ease-expo hover:-translate-y-1 hover:shadow-lift"
        >
          <div className="rounded-core relative overflow-hidden bg-ink px-7 py-8 sm:px-10 sm:py-10">
            <div
              className="pointer-events-none absolute inset-0"
              style={{
                background:
                  'radial-gradient(30rem 20rem at 85% 0%, rgba(156,122,22,0.5), transparent 60%), radial-gradient(24rem 20rem at 10% 120%, rgba(18,122,84,0.25), transparent 60%)',
              }}
            />
            <div className="relative flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
              <div className="max-w-lg">
                <span className="inline-flex items-center gap-2 rounded-pill border border-white/15 bg-white/5 px-3 py-1 font-mono text-[10px] font-medium uppercase tracking-eyebrow text-white/70">
                  <Sparkles size={11} className="text-gold" /> Motor de auditoria
                </span>
                <h3 className="mt-4 font-display text-[26px] font-semibold leading-tight tracking-tight text-white sm:text-[30px]">
                  Auditoria RIT automatizada
                </h3>
                <p className="mt-2.5 text-[14px] leading-relaxed text-white/55">
                  Envie os anexos do balanço em PDF. O Kora extrai os quadros contábeis, gera a
                  planilha de trabalho e produz o relatório de inspeção (RIT) com apoio de IA.
                </p>
                <div className="mt-5 flex flex-wrap gap-2">
                  {['Quadros contábeis', 'Excel de trabalho', 'RIT + análise de IA'].map((t) => (
                    <span key={t} className="rounded-pill bg-white/8 px-3 py-1 text-[11.5px] font-medium text-white/70 ring-1 ring-inset ring-white/10">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
              <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-white/10 text-white ring-1 ring-inset ring-white/15 transition-all duration-500 ease-expo group-hover:bg-gold group-hover:translate-x-1 group-hover:-translate-y-1">
                <ArrowUpRight size={24} strokeWidth={1.75} />
              </span>
            </div>
          </div>
        </Link>
      </Reveal>

      {/* RGF + RREO */}
      <div className="grid gap-5 sm:grid-cols-2">
        {TOOLS.map((tool, i) => (
          <Reveal key={tool.to} delay={120 + i * 80}>
            <Link
              to={tool.to}
              className="group flex h-full flex-col rounded-3xl border border-stone-200/80 bg-surface p-6 shadow-card transition-all duration-400 ease-expo hover:-translate-y-1 hover:border-gold-ring hover:shadow-lift"
            >
              <div className="mb-5 flex items-center justify-between">
                <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gold-wash text-gold transition-colors duration-300 group-hover:bg-gold group-hover:text-white">
                  <tool.icon size={22} strokeWidth={1.6} />
                </span>
                <Badge tone="neutral">{tool.tag}</Badge>
              </div>
              <h3 className="font-display text-[19px] font-semibold tracking-tight text-ink">{tool.title}</h3>
              <p className="mt-2 flex-1 text-[13.5px] leading-relaxed text-stone-500">{tool.desc}</p>
              <span className="mt-5 inline-flex items-center gap-1.5 text-[13px] font-semibold text-gold">
                Abrir ferramenta
                <ArrowRight size={15} className="transition-transform duration-300 ease-expo group-hover:translate-x-1" />
              </span>
            </Link>
          </Reveal>
        ))}
      </div>

      {/* ── Municípios ── */}
      <div className="mb-4 mt-12 flex items-center gap-2.5">
        <h2 className="font-display text-[13px] font-semibold uppercase tracking-eyebrow text-stone-400">Municípios</h2>
        <div className="h-px flex-1 bg-stone-200/70" />
        <Link to="/municipios" className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-gold hover:text-gold-hover">
          Ver todos <ArrowRight size={13} />
        </Link>
      </div>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => <div key={i} className="skeleton h-24" />)}
        </div>
      ) : prefeituras.length === 0 ? (
        <div className="rounded-3xl border border-stone-200/80 bg-surface shadow-card">
          <EmptyState
            icon={Building2}
            title="Nenhum município disponível"
            action={
              isAdmin ? (
                <Link to="/municipios" className="mt-1 inline-flex items-center gap-1.5 text-[13px] font-semibold text-gold hover:text-gold-hover">
                  <Plus size={14} /> Cadastrar prefeitura
                </Link>
              ) : null
            }
          >
            {isAdmin ? 'Cadastre a primeira prefeitura para começar.' : 'Você ainda não está vinculado a nenhuma prefeitura.'}
          </EmptyState>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((p, i) => (
            <Reveal key={p.id} delay={i * 50}>
              <Link
                to={`/municipios/${p.id}`}
                className="group flex items-center gap-3.5 rounded-2xl border border-stone-200/80 bg-surface p-4 shadow-soft transition-all duration-300 ease-expo hover:-translate-y-0.5 hover:border-gold-ring hover:shadow-card"
              >
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-stone-100 text-stone-500 transition-colors group-hover:bg-gold-wash group-hover:text-gold">
                  <Building2 size={19} strokeWidth={1.6} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-semibold tracking-tight text-ink">{p.municipio}</p>
                  <p className="truncate text-[12px] text-stone-400">{p.nome}</p>
                </div>
                <span className="flex items-center gap-1.5">
                  <span className="rounded-pill bg-stone-100 px-2 py-0.5 font-mono text-[10.5px] font-semibold text-stone-500">{p.uf}</span>
                  <ArrowUpRight size={15} className="text-stone-300 transition-all duration-300 ease-expo group-hover:text-gold group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                </span>
              </Link>
            </Reveal>
          ))}
          {prefeituras.length > 6 && (
            <Link
              to="/municipios"
              className="flex items-center justify-center gap-2 rounded-2xl border border-dashed border-stone-300 bg-stone-50 p-4 text-[13px] font-semibold text-stone-500 transition-colors hover:border-gold hover:text-gold"
            >
              +{prefeituras.length - 6} municípios <ArrowRight size={14} />
            </Link>
          )}
        </div>
      )}
    </div>
  )
}
