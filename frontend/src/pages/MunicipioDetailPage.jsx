import { useState, useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft, Building2, FileSpreadsheet, Layers, ScanSearch, Archive, ArchiveRestore,
  CheckCircle2, AlertTriangle, AlertOctagon, Clock,
} from 'lucide-react'
import { api } from '../lib/api'
import { cn } from '../lib/cn'
import { Badge, Spinner, EmptyState, Reveal } from '../ui'
import { useReveal } from '../hooks/useReveal'

const TIPO_LABEL = { RGF_SIMPLIFICADO: 'RGF', RREO: 'RREO' }

const STATUS = {
  sem_divergencias: { tone: 'success', label: 'Sem divergências', icon: CheckCircle2, wrap: 'bg-success-bg text-success' },
  com_divergencias: { tone: 'danger', label: 'Divergências críticas', icon: AlertOctagon, wrap: 'bg-danger-bg text-danger' },
  concluida: { tone: 'warning', label: 'Concluída com divergências', icon: AlertTriangle, wrap: 'bg-warning-bg text-warning' },
  pendente: { tone: 'neutral', label: 'Pendente', icon: Clock, wrap: 'bg-stone-100 text-stone-500' },
}

function fmtDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' }) +
    ' · ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
}

export default function MunicipioDetailPage() {
  const { id } = useParams()
  const [loading, setLoading] = useState(true)
  const ref = useReveal([loading])
  const [pref, setPref] = useState(null)
  const [concs, setConcs] = useState([])
  const [err, setErr] = useState('')
  const [archiving, setArchiving] = useState(null)

  async function fetchData() {
    setLoading(true)
    try {
      const res = await api.get(`/prefeituras/${id}/conciliacoes`)
      if (!res.ok) throw new Error('Município não encontrado ou sem acesso.')
      const data = await res.json()
      setPref(data.prefeitura)
      setConcs(data.conciliacoes || [])
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { fetchData() }, [id])

  async function toggleArchive(c) {
    setArchiving(c.id)
    try {
      const res = await api.patch(`/conciliacoes/${c.id}/arquivar`)
      if (res.ok) await fetchData()
    } finally {
      setArchiving(null)
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center py-24 text-gold"><Spinner size={24} /></div>
  }

  if (err || !pref) {
    return (
      <div>
        <Link to="/municipios" className="mb-6 inline-flex items-center gap-1.5 text-[13px] font-semibold text-stone-500 hover:text-ink">
          <ArrowLeft size={15} /> Municípios
        </Link>
        <div className="rounded-3xl border border-stone-200/80 bg-surface shadow-card">
          <EmptyState icon={Building2} title="Não foi possível carregar">{err}</EmptyState>
        </div>
      </div>
    )
  }

  const visiveis = concs.filter((c) => !c.arquivado)
  const arquivadas = concs.filter((c) => c.arquivado)

  const ACTIONS = [
    { to: '/conciliacao/rgf', icon: FileSpreadsheet, label: 'Conciliação RGF' },
    { to: '/conciliacao/rreo', icon: Layers, label: 'Conciliação RREO' },
    { to: '/auditoria', icon: ScanSearch, label: 'Auditoria RIT' },
  ]

  return (
    <div ref={ref}>
      <Link to="/municipios" className="mb-6 inline-flex items-center gap-1.5 text-[13px] font-semibold text-stone-500 transition-colors hover:text-ink">
        <ArrowLeft size={15} /> Municípios
      </Link>

      {/* Header */}
      <Reveal className="mb-6 overflow-hidden rounded-[1.75rem] border border-stone-200/70 bg-stone-100/50 p-1.5 shadow-card">
        <div className="rounded-core flex flex-col gap-5 bg-surface p-6 sm:flex-row sm:items-center sm:justify-between sm:p-8">
          <div className="flex items-center gap-4">
            <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-ink text-white">
              <Building2 size={24} strokeWidth={1.6} />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-display text-[24px] font-semibold tracking-tight text-ink">{pref.municipio}</h1>
                <span className="rounded-pill bg-stone-100 px-2 py-0.5 font-mono text-[11px] font-semibold text-stone-500">{pref.uf}</span>
              </div>
              <p className="mt-0.5 text-[13px] text-stone-500">{pref.nome}</p>
            </div>
          </div>
          <Badge tone="neutral">{concs.length} conciliaç{concs.length === 1 ? 'ão' : 'ões'}</Badge>
        </div>
      </Reveal>

      {/* Quick actions */}
      <Reveal delay={60} className="mb-8 grid gap-3 sm:grid-cols-3">
        {ACTIONS.map((a) => (
          <Link
            key={a.to}
            to={a.to}
            className="group flex items-center gap-3 rounded-2xl border border-stone-200/80 bg-surface p-4 shadow-soft transition-all duration-300 ease-expo hover:-translate-y-0.5 hover:border-gold-ring hover:shadow-card"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gold-wash text-gold transition-colors group-hover:bg-gold group-hover:text-white">
              <a.icon size={18} strokeWidth={1.6} />
            </span>
            <span className="text-[13.5px] font-semibold tracking-tight text-ink">{a.label}</span>
          </Link>
        ))}
      </Reveal>

      {/* History */}
      <div className="mb-4 flex items-center gap-2.5">
        <h2 className="font-display text-[13px] font-semibold uppercase tracking-eyebrow text-stone-400">Histórico</h2>
        <div className="h-px flex-1 bg-stone-200/70" />
      </div>

      {visiveis.length === 0 ? (
        <div className="rounded-3xl border border-stone-200/80 bg-surface shadow-card">
          <EmptyState icon={Clock} title="Nenhuma conciliação ainda">
            Use as ferramentas acima para gerar a primeira conciliação deste município.
          </EmptyState>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {visiveis.map((c, i) => (
            <ConcRow key={c.id} c={c} delay={i * 40} archiving={archiving === c.id} onArchive={() => toggleArchive(c)} />
          ))}
        </div>
      )}

      {arquivadas.length > 0 && (
        <>
          <div className="mb-4 mt-10 flex items-center gap-2.5">
            <h2 className="font-display text-[13px] font-semibold uppercase tracking-eyebrow text-stone-400">Arquivadas</h2>
            <div className="h-px flex-1 bg-stone-200/70" />
          </div>
          <div className="flex flex-col gap-3">
            {arquivadas.map((c) => (
              <ConcRow key={c.id} c={c} archived archiving={archiving === c.id} onArchive={() => toggleArchive(c)} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function ConcRow({ c, delay = 0, archived = false, archiving, onArchive }) {
  const st = STATUS[c.status] || STATUS.pendente
  const StIcon = st.icon
  const tipo = TIPO_LABEL[c.tipo] || c.tipo
  return (
    <Reveal
      delay={delay}
      className={cn(
        'flex flex-wrap items-center gap-4 rounded-2xl border border-stone-200/80 bg-surface p-4 shadow-soft transition-all duration-300 ease-expo hover:shadow-card',
        archived && 'opacity-60',
      )}
    >
      <span className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-xl', st.wrap)}>
        <StIcon size={19} strokeWidth={1.75} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] font-semibold text-gold">{tipo}</span>
          <span className="text-[12.5px] text-stone-400">{fmtDate(c.criado_em)}</span>
        </div>
        <p className="mt-0.5 text-[13.5px] font-medium text-ink">
          {c.total_divergencias === 0
            ? 'Sem divergências'
            : `${c.total_divergencias} divergência${c.total_divergencias > 1 ? 's' : ''}`}
          {c.criado_por_nome && <span className="font-normal text-stone-400"> · por {c.criado_por_nome}</span>}
        </p>
      </div>
      <Badge tone={st.tone}>{st.label}</Badge>
      <button
        onClick={onArchive}
        disabled={archiving}
        title={archived ? 'Desarquivar' : 'Arquivar'}
        className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-ink"
      >
        {archiving ? <Spinner size={13} /> : archived ? <ArchiveRestore size={15} /> : <Archive size={15} />}
      </button>
    </Reveal>
  )
}
