import { AlertOctagon, AlertTriangle, CheckCircle2, ShieldAlert, Scale, FileWarning } from 'lucide-react'
import { cn } from '../lib/cn'
import { Badge, Reveal } from '../ui'
import { useReveal } from '../hooks/useReveal'

const TIPO = {
  IRREGULAR: { tone: 'danger', icon: AlertOctagon, label: 'Irregular', bar: '#C33421' },
  ALERTA: { tone: 'warning', icon: AlertTriangle, label: 'Alerta', bar: '#B26A00' },
}

function fmtValor(v) {
  if (v == null) return '—'
  if (typeof v === 'number') {
    return v.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }
  return String(v)
}

export default function AuditResult({ data }) {
  const ref = useReveal([])
  if (!data) return null

  const municipio = data.municipio || '—'
  const exercicio = data.exercicio || ''
  const incs = data.inconformidades || []
  const resumo = data.resumo || {}
  const iaErro = data._erro_ia
  const ausentes = resumo.quadros_ausentes || []

  const irregulares = resumo.irregulares ?? incs.filter((i) => i.tipo === 'IRREGULAR').length
  const alertas = resumo.alertas ?? incs.filter((i) => i.tipo === 'ALERTA').length
  const analisados = resumo.quadros_analisados ?? (data.quadros_gerados || []).length

  return (
    <div ref={ref} className="mt-6">
      {/* Hero summary */}
      <Reveal className="overflow-hidden rounded-3xl border border-stone-200/80 bg-surface shadow-card">
        <div className="flex flex-col gap-4 border-b border-stone-200/70 p-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <span className={cn('flex h-14 w-14 items-center justify-center rounded-2xl', irregulares > 0 ? 'bg-danger-bg text-danger' : alertas > 0 ? 'bg-warning-bg text-warning' : 'bg-success-bg text-success')}>
              {irregulares > 0 ? <ShieldAlert size={24} strokeWidth={1.75} /> : alertas > 0 ? <AlertTriangle size={24} strokeWidth={1.75} /> : <CheckCircle2 size={24} strokeWidth={1.75} />}
            </span>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-eyebrow text-stone-400">Análise concluída</p>
              <h3 className="font-display text-[20px] font-semibold tracking-tight text-ink">
                {municipio} {exercicio && <span className="text-stone-400">· {exercicio}</span>}
              </h3>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone="danger">{irregulares} irregular{irregulares !== 1 ? 'es' : ''}</Badge>
            <Badge tone="warning">{alertas} alerta{alertas !== 1 ? 's' : ''}</Badge>
            <Badge tone="neutral">{analisados} quadros</Badge>
          </div>
        </div>

        {iaErro && (
          <div className="flex items-start gap-2 border-b border-stone-200/70 bg-warning-bg/60 px-6 py-3 text-[12.5px] font-medium text-warning">
            <FileWarning size={15} className="mt-0.5 shrink-0" />
            <span>Refino por IA indisponível ({iaErro}). Os achados abaixo vêm do motor de regras.</span>
          </div>
        )}

        {/* Inconformidades */}
        <div className="p-4 sm:p-6">
          {incs.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <CheckCircle2 size={30} className="text-success" strokeWidth={1.5} />
              <p className="font-display text-[15px] font-semibold text-ink">Nenhuma inconformidade detectada</p>
              <p className="text-[13px] text-stone-500">Todos os quadros analisados estão dentro dos limites legais.</p>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {incs.map((inc, i) => {
                const cfg = TIPO[inc.tipo] || TIPO.ALERTA
                const Icon = cfg.icon
                return (
                  <Reveal
                    key={i}
                    delay={i * 40}
                    className="relative flex gap-4 overflow-hidden rounded-2xl border border-stone-200/70 bg-surface p-4 shadow-soft"
                  >
                    <span className="absolute left-0 top-0 h-full w-1" style={{ background: cfg.bar }} />
                    <span className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-xl', inc.tipo === 'IRREGULAR' ? 'bg-danger-bg text-danger' : 'bg-warning-bg text-warning')}>
                      <Icon size={18} strokeWidth={1.75} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={cfg.tone}>{cfg.label}</Badge>
                        {inc.dimensao && <Badge tone="neutral">{inc.dimensao}</Badge>}
                        {inc.quadro && (
                          <span className="font-mono text-[11px] font-medium text-stone-400">
                            {String(inc.quadro).replace('quadro_', 'Q').replace(/^Q0?/, 'Q')}
                          </span>
                        )}
                      </div>
                      {inc.titulo && <p className="mt-1.5 text-[14px] font-semibold tracking-tight text-ink">{inc.titulo}</p>}
                      <p className="mt-1 text-[13.5px] leading-relaxed text-stone-600">{inc.descricao}</p>
                      <div className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-stone-500">
                        {inc.valor_apurado != null && (
                          <span>Apurado: <span className="font-semibold text-ink tnum">{fmtValor(inc.valor_apurado)}</span></span>
                        )}
                        {inc.limite_legal && (
                          <span>Limite: <span className="font-semibold text-ink">{inc.limite_legal}</span></span>
                        )}
                        {inc.base_legal && (
                          <span className="inline-flex items-center gap-1">
                            <Scale size={12} className="text-stone-400" /> {inc.base_legal}
                          </span>
                        )}
                      </div>
                    </div>
                  </Reveal>
                )
              })}
            </div>
          )}

          {ausentes.length > 0 && (
            <div className="mt-4 rounded-2xl bg-stone-50 px-4 py-3">
              <p className="text-[12px] text-stone-500">
                <span className="font-semibold text-stone-600">Quadros ausentes:</span>{' '}
                {ausentes.map((q) => String(q).replace('quadro_', 'Q')).join(', ')} — envie os documentos correspondentes para análise completa.
              </p>
            </div>
          )}
        </div>
      </Reveal>
    </div>
  )
}
