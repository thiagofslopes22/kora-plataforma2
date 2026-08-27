import { useState } from 'react'
import { Download, RefreshCw, CheckCircle2, AlertTriangle, Info } from 'lucide-react'
import { downloadBlob } from '../lib/api'
import { cn } from '../lib/cn'
import { Reveal } from '../ui'
import { useReveal } from '../hooks/useReveal'

const SEV = {
  'CRÍTICA':       { color: '#C33421', bg: '#FBE8E4', label: 'Crítica' },
  'SIGNIFICATIVA': { color: '#B26A00', bg: '#FBF0DB', label: 'Significativa' },
  'MODERADA':      { color: '#C0A100', bg: '#FBF6DD', label: 'Moderada' },
  'BAIXA':         { color: '#127A54', bg: '#E5F3EC', label: 'Baixa' },
  'MÍNIMA':        { color: '#3A9E6E', bg: '#E9F5EF', label: 'Mínima' },
  'AUSENTE':       { color: '#2E5BD8', bg: '#E8EDFC', label: 'Ausente' },
}
const ORDER = ['CRÍTICA', 'SIGNIFICATIVA', 'MODERADA', 'BAIXA', 'MÍNIMA', 'AUSENTE']

export default function RgfResult({ data, onReset }) {
  const ref = useReveal([])
  const [downloading, setDownloading] = useState(false)
  if (!data) return null

  const { job_id, stats } = data
  const total = stats.total_divergencias || 0
  const sevs = stats.por_severidade || {}
  const porAnexo = stats.por_anexo || {}
  const hasCritical = (sevs['CRÍTICA'] || 0) + (sevs['SIGNIFICATIVA'] || 0) > 0
  const maxAnexo = Math.max(...Object.values(porAnexo), 1)

  async function handleDownload() {
    setDownloading(true)
    try {
      await downloadBlob(`/download/${job_id}`, 'RGF_Conciliado.xlsx')
    } catch (e) {
      alert('Erro no download: ' + e.message)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div ref={ref}>
      {/* Hero */}
      <Reveal className="mb-6 flex items-center gap-4 rounded-3xl border border-stone-200/80 bg-surface p-6 shadow-card">
        <span className={cn('flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl', hasCritical ? 'bg-warning-bg text-warning' : 'bg-success-bg text-success')}>
          {hasCritical ? <AlertTriangle size={26} strokeWidth={1.75} /> : <CheckCircle2 size={26} strokeWidth={1.75} />}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-[22px] font-semibold tracking-tight text-ink">Conciliação concluída</h2>
          <p className="mt-0.5 text-[14px] text-stone-500">
            {total === 0
              ? 'Nenhuma divergência — arquivos idênticos.'
              : `${total} célula${total > 1 ? 's' : ''} com divergência identificada${total > 1 ? 's' : ''}.`}
          </p>
        </div>
        {total > 0 && (
          <div className="hidden shrink-0 flex-col items-end sm:flex">
            <span className="font-display text-[34px] font-semibold leading-none tracking-tighter text-ink tnum">{total}</span>
            <span className="text-[11.5px] uppercase tracking-eyebrow text-stone-400">divergências</span>
          </div>
        )}
      </Reveal>

      {total > 0 && (
        <>
          {/* Severity */}
          <Reveal delay={60} className="mb-5 rounded-3xl border border-stone-200/80 bg-surface p-6 shadow-card">
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-eyebrow text-stone-400">Por classificação</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {ORDER.map((key) => {
                const count = sevs[key] || 0
                if (!count) return null
                const cfg = SEV[key]
                return (
                  <div key={key} className="rounded-2xl border border-stone-200/70 p-4" style={{ background: cfg.bg }}>
                    <div className="flex items-center justify-between">
                      <span className="text-[13px] font-semibold" style={{ color: cfg.color }}>{cfg.label}</span>
                      <span className="font-display text-[22px] font-semibold leading-none tnum" style={{ color: cfg.color }}>{count}</span>
                    </div>
                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/60">
                      <div className="h-full origin-left rounded-full" style={{ width: `${(count / total) * 100}%`, background: cfg.color }} />
                    </div>
                  </div>
                )
              })}
            </div>
          </Reveal>

          {/* Per anexo */}
          {Object.keys(porAnexo).length > 0 && (
            <Reveal delay={100} className="mb-6 rounded-3xl border border-stone-200/80 bg-surface p-6 shadow-card">
              <p className="mb-4 text-[11px] font-semibold uppercase tracking-eyebrow text-stone-400">Por anexo</p>
              <div className="flex flex-col gap-3">
                {Object.entries(porAnexo).sort(([, a], [, b]) => b - a).map(([name, count]) => (
                  <div key={name} className="flex items-center gap-4">
                    <span className="w-40 shrink-0 truncate text-[13px] font-medium text-ink">{name}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-stone-100">
                      <div className="h-full rounded-full bg-gold" style={{ width: `${(count / maxAnexo) * 100}%` }} />
                    </div>
                    <span className="w-8 shrink-0 text-right text-[13px] font-semibold text-stone-500 tnum">{count}</span>
                  </div>
                ))}
              </div>
            </Reveal>
          )}
        </>
      )}

      {/* Actions */}
      <Reveal delay={140} className="flex flex-col gap-3 sm:flex-row">
        <button
          onClick={handleDownload}
          disabled={downloading}
          className="group flex h-[52px] flex-1 items-center justify-center gap-2.5 rounded-pill bg-gold pl-6 pr-3 font-semibold text-white shadow-[0_1px_2px_rgba(90,71,14,0.35),0_14px_30px_-10px_rgba(156,122,22,0.7)] transition-all duration-300 ease-expo hover:bg-gold-hover active:scale-[0.99] disabled:opacity-50"
        >
          <span>{downloading ? 'Preparando…' : 'Baixar planilha conciliada (.xlsx)'}</span>
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/15 transition-transform duration-300 ease-expo group-hover:translate-x-0.5 group-hover:scale-105">
            <Download size={16} />
          </span>
        </button>
        <button
          onClick={onReset}
          className="flex h-[52px] items-center justify-center gap-2 rounded-pill border border-stone-200 bg-surface px-6 text-[14px] font-semibold text-stone-600 shadow-soft transition-all duration-300 ease-expo hover:border-stone-300 hover:text-ink active:scale-[0.99]"
        >
          <RefreshCw size={15} /> Nova conciliação
        </button>
      </Reveal>

      <div className="mt-5 flex items-start gap-2 text-[12.5px] leading-relaxed text-stone-400">
        <Info size={14} className="mt-0.5 shrink-0" />
        <span>A planilha baixada é uma cópia fiel do rascunho, com as células divergentes coloridas por criticidade. Passe o cursor sobre cada célula para ver o valor do SICONFI e a diferença calculada.</span>
      </div>
    </div>
  )
}
