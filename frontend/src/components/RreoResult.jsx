import { useState } from 'react'
import { Download, RefreshCw, CheckCircle2, AlertTriangle, Info, BookOpen } from 'lucide-react'
import { downloadBlob } from '../lib/api'
import { cn } from '../lib/cn'
import { Reveal } from '../ui'
import { useReveal } from '../hooks/useReveal'

const SEV = {
  'CRÍTICA':         { color: '#C33421', bg: '#FBE8E4', label: 'Crítica' },
  'SIGNIFICATIVA':   { color: '#B26A00', bg: '#FBF0DB', label: 'Significativa' },
  'MODERADA':        { color: '#C0A100', bg: '#FBF6DD', label: 'Moderada' },
  'BAIXA':           { color: '#127A54', bg: '#E5F3EC', label: 'Baixa' },
  'MÍNIMA':          { color: '#3A9E6E', bg: '#E9F5EF', label: 'Mínima' },
  'AUSENTE_MSC':     { color: '#2E5BD8', bg: '#E8EDFC', label: 'Ausente MSC' },
  'AUSENTE_SICONFI': { color: '#6D4BC7', bg: '#F1ECFB', label: 'Ausente SICONFI' },
  'TEXTO':           { color: '#7C766B', bg: '#F3F1EC', label: 'Texto' },
}
const ORDER = ['CRÍTICA', 'SIGNIFICATIVA', 'MODERADA', 'BAIXA', 'MÍNIMA', 'AUSENTE_MSC', 'AUSENTE_SICONFI', 'TEXTO']

export default function RreoResult({ data, onReset }) {
  const ref = useReveal([])
  const [busy, setBusy] = useState('')
  if (!data) return null

  const { job_id, stats } = data
  const total = stats.total_divergencias ?? 0
  const porClass = stats.por_classificacao ?? {}
  const porSheet = stats.por_sheet ?? {}
  const avisos = stats.avisos ?? []
  const sheets = stats.sheets_comparadas ?? []
  const criticas = (porClass['CRÍTICA'] ?? 0) + (porClass['SIGNIFICATIVA'] ?? 0)
  const maxSheet = Math.max(...Object.values(porSheet), 1)

  async function baixar(which, endpoint, filename) {
    setBusy(which)
    try {
      await downloadBlob(endpoint, filename)
    } catch (e) {
      alert('Erro no download: ' + e.message)
    } finally {
      setBusy('')
    }
  }

  return (
    <div ref={ref}>
      {/* Hero */}
      <Reveal className="mb-6 flex items-center gap-4 rounded-3xl border border-stone-200/80 bg-surface p-6 shadow-card">
        <span className={cn('flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl', criticas > 0 ? 'bg-warning-bg text-warning' : 'bg-success-bg text-success')}>
          {criticas > 0 ? <AlertTriangle size={26} strokeWidth={1.75} /> : <CheckCircle2 size={26} strokeWidth={1.75} />}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-[22px] font-semibold tracking-tight text-ink">Conciliação RREO concluída</h2>
          <p className="mt-0.5 text-[14px] text-stone-500">
            {total === 0
              ? 'Nenhuma divergência — RREO e SICONFI idênticos.'
              : `${total} divergência${total > 1 ? 's' : ''} em ${sheets.length} anexo${sheets.length !== 1 ? 's' : ''}.`}
          </p>
        </div>
        {total > 0 && (
          <div className="hidden shrink-0 flex-col items-end sm:flex">
            <span className="font-display text-[34px] font-semibold leading-none tracking-tighter text-ink tnum">{total}</span>
            <span className="text-[11.5px] uppercase tracking-eyebrow text-stone-400">divergências</span>
          </div>
        )}
      </Reveal>

      {avisos.length > 0 && (
        <Reveal delay={40} className="mb-5 flex flex-col gap-1.5 rounded-2xl border border-info-ring bg-info-bg px-4 py-3">
          {avisos.map((a, i) => (
            <div key={i} className="flex items-start gap-2 text-[12.5px] font-medium text-info">
              <Info size={14} className="mt-0.5 shrink-0" /> <span>{a}</span>
            </div>
          ))}
        </Reveal>
      )}

      {total > 0 && (
        <>
          <Reveal delay={60} className="mb-5 rounded-3xl border border-stone-200/80 bg-surface p-6 shadow-card">
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-eyebrow text-stone-400">Por classificação</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {ORDER.map((key) => {
                const count = porClass[key]
                if (!count) return null
                const cfg = SEV[key]
                return (
                  <div key={key} className="rounded-2xl border border-stone-200/70 p-4" style={{ background: cfg.bg }}>
                    <div className="flex items-center justify-between">
                      <span className="text-[12.5px] font-semibold" style={{ color: cfg.color }}>{cfg.label}</span>
                      <span className="font-display text-[20px] font-semibold leading-none tnum" style={{ color: cfg.color }}>{count}</span>
                    </div>
                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/60">
                      <div className="h-full rounded-full" style={{ width: `${(count / total) * 100}%`, background: cfg.color }} />
                    </div>
                  </div>
                )
              })}
            </div>
          </Reveal>

          {Object.keys(porSheet).length > 0 && (
            <Reveal delay={100} className="mb-6 rounded-3xl border border-stone-200/80 bg-surface p-6 shadow-card">
              <div className="mb-4 flex items-center justify-between">
                <p className="text-[11px] font-semibold uppercase tracking-eyebrow text-stone-400">Por anexo</p>
                <span className="rounded-pill bg-stone-100 px-2.5 py-0.5 text-[11.5px] font-semibold text-stone-500">{sheets.length} comparados</span>
              </div>
              <div className="flex flex-col gap-3">
                {Object.entries(porSheet).sort(([, a], [, b]) => b - a).map(([nome, count]) => (
                  <div key={nome} className="flex items-center gap-4">
                    <span className="w-36 shrink-0 truncate text-[13px] font-medium text-ink">{nome.replace('RREO-', '')}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-stone-100">
                      <div className="h-full rounded-full bg-gold" style={{ width: `${(count / maxSheet) * 100}%` }} />
                    </div>
                    <span className="w-8 shrink-0 text-right text-[13px] font-semibold text-stone-500 tnum">{count}</span>
                  </div>
                ))}
              </div>
            </Reveal>
          )}
        </>
      )}

      {/* Downloads */}
      <Reveal delay={140} className="grid gap-3 sm:grid-cols-2">
        <button
          onClick={() => baixar('a', `/download/${job_id}`, 'RREO_Divergencias_Destacadas.xlsx')}
          disabled={busy === 'a'}
          className="group flex items-center gap-3.5 rounded-2xl bg-gold p-4 text-left text-white shadow-[0_1px_2px_rgba(90,71,14,0.35),0_14px_30px_-10px_rgba(156,122,22,0.7)] transition-all duration-300 ease-expo hover:bg-gold-hover active:scale-[0.99] disabled:opacity-50"
        >
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/15">
            <Download size={19} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13.5px] font-semibold">Planilha com divergências</span>
            <span className="block text-[11.5px] text-white/70">Cópia do rascunho, células por criticidade</span>
          </span>
        </button>
        <button
          onClick={() => baixar('b', `/download-auditoria/${job_id}`, 'RREO_Relatorio_Auditoria_Kora.xlsx')}
          disabled={busy === 'b'}
          className="group flex items-center gap-3.5 rounded-2xl border border-stone-200 bg-surface p-4 text-left shadow-soft transition-all duration-300 ease-expo hover:border-gold-ring hover:shadow-card active:scale-[0.99] disabled:opacity-50"
        >
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-stone-100 text-stone-500">
            <BookOpen size={19} strokeWidth={1.75} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13.5px] font-semibold text-ink">Relatório de auditoria</span>
            <span className="block text-[11.5px] text-stone-400">Layout Kora, para apresentar e arquivar</span>
          </span>
        </button>
      </Reveal>

      <Reveal delay={180} className="mt-6 flex flex-col items-center gap-3">
        <button
          onClick={onReset}
          className="inline-flex items-center gap-2 rounded-pill border border-stone-200 bg-surface px-5 py-2.5 text-[13.5px] font-semibold text-stone-600 shadow-soft transition-all duration-300 ease-expo hover:border-stone-300 hover:text-ink"
        >
          <RefreshCw size={14} /> Nova conciliação RREO
        </button>
        <p className="max-w-lg text-center text-[12px] leading-relaxed text-stone-400">
          A planilha destacada é cópia fiel do rascunho — passe o cursor sobre cada célula para ver o valor do SICONFI e a diferença. O relatório de auditoria é um resumo tabular pronto para revisão.
        </p>
      </Reveal>
    </div>
  )
}
