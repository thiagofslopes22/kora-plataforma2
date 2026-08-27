import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Building2, Info, ArrowRight } from 'lucide-react'
import { FileDrop } from './FileDrop'
import { Select, Eyebrow, Reveal } from '../ui'
import { useReveal } from '../hooks/useReveal'

const SEV_LEGEND = [
  { color: '#C33421', label: 'Crítica', desc: '> 20%' },
  { color: '#B26A00', label: 'Significativa', desc: '5–20%' },
  { color: '#C0A100', label: 'Moderada', desc: '1–5%' },
  { color: '#127A54', label: 'Baixa', desc: '< 1%' },
  { color: '#2E5BD8', label: 'Ausente', desc: 'campo faltando' },
]

const HOW = [
  { n: '01', t: 'Selecione o município', d: 'Vincula o resultado ao histórico da prefeitura' },
  { n: '02', t: 'Envie os dois arquivos', d: 'O rascunho e o arquivo homologado' },
  { n: '03', t: 'Comparação automática', d: 'Célula a célula, preservando o layout original' },
  { n: '04', t: 'Baixe o resultado', d: 'Planilha com divergências marcadas por criticidade' },
]

export default function ConciliacaoUpload({
  prefeituras,
  selected,
  onSelect,
  onSubmit,
  labels,
}) {
  const [rascunho, setRascunho] = useState(null)
  const [homologado, setHomologado] = useState(null)
  const ref = useReveal([])

  const ready = rascunho && homologado && selected

  const options = prefeituras.map((p) => ({
    value: p.id,
    label: `${p.municipio} · ${p.uf}`,
    p,
  }))

  return (
    <div ref={ref}>
      {/* Prefeitura + files card */}
      <Reveal className="rounded-[1.75rem] border border-stone-200/70 bg-stone-100/50 p-1.5 shadow-card">
        <div className="rounded-core bg-surface p-6 sm:p-8">
          {/* Prefeitura */}
          <div className="mb-6">
            <div className="mb-2 flex items-center gap-1.5 text-[12.5px] font-semibold tracking-tight text-stone-600">
              <Building2 size={14} className="text-stone-400" />
              Município
              <span className="text-danger">*</span>
            </div>
            <Select
              value={selected?.id ?? null}
              onChange={(_, o) => onSelect(o.p)}
              options={options}
              placeholder="Selecione o município…"
              className="max-w-md"
              renderOption={(o) => (
                <span className="flex flex-col">
                  <span className="text-[13.5px] font-medium text-ink">{o.p.municipio}</span>
                  <span className="text-[11.5px] text-stone-400">{o.p.nome} · {o.p.uf}</span>
                </span>
              )}
            />
            {prefeituras.length === 0 && (
              <p className="mt-2 text-[12.5px] text-stone-400">
                Nenhum município disponível.{' '}
                <Link to="/municipios" className="font-semibold text-gold hover:text-gold-hover">Cadastrar →</Link>
              </p>
            )}
          </div>

          <div className="mb-6 h-px bg-stone-200/70" />

          {/* File zones */}
          <div className="grid gap-4 md:grid-cols-2">
            <FileDrop
              label={labels.rascunhoLabel}
              subtitle={labels.rascunhoSub}
              kind="xls"
              file={rascunho}
              onFile={setRascunho}
              onClear={() => setRascunho(null)}
            />
            <FileDrop
              label={labels.homologadoLabel}
              subtitle={labels.homologadoSub}
              kind="xls"
              file={homologado}
              onFile={setHomologado}
              onClear={() => setHomologado(null)}
            />
          </div>

          {!selected && (rascunho || homologado) && (
            <div className="mt-4 flex items-center gap-2 rounded-xl bg-warning-bg px-3.5 py-2.5 text-[12.5px] font-medium text-warning">
              <Info size={14} /> Selecione o município antes de processar.
            </div>
          )}

          <button
            onClick={() => onSubmit({ rascunho, homologado })}
            disabled={!ready}
            className="group mt-6 flex h-[52px] w-full items-center justify-center gap-2 rounded-pill bg-gold pl-6 pr-3 font-semibold text-white shadow-[0_1px_2px_rgba(90,71,14,0.35),0_14px_30px_-10px_rgba(156,122,22,0.7)] transition-all duration-300 ease-expo hover:bg-gold-hover active:scale-[0.99] disabled:pointer-events-none disabled:opacity-40"
          >
            <span>{labels.btn}</span>
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/15 transition-transform duration-300 ease-expo group-hover:translate-x-0.5 group-hover:scale-105">
              <ArrowRight size={17} />
            </span>
          </button>
        </div>
      </Reveal>

      {/* How it works */}
      <Reveal delay={80} className="mt-6 grid gap-5 rounded-3xl border border-stone-200/80 bg-surface p-6 shadow-card lg:grid-cols-[1.4fr_1fr] lg:p-8">
        <div>
          <Eyebrow className="mb-4">Como funciona</Eyebrow>
          <div className="grid gap-4 sm:grid-cols-2">
            {HOW.map((s) => (
              <div key={s.n} className="flex gap-3">
                <span className="font-mono text-[12px] font-semibold text-gold">{s.n}</span>
                <div>
                  <p className="text-[13.5px] font-semibold tracking-tight text-ink">{s.t}</p>
                  <p className="mt-0.5 text-[12.5px] leading-snug text-stone-500">{s.d}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-2xl bg-stone-50 p-5">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-eyebrow text-stone-400">Escala de criticidade</p>
          <div className="flex flex-col gap-2.5">
            {SEV_LEGEND.map((s) => (
              <div key={s.label} className="flex items-center gap-2.5">
                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: s.color }} />
                <span className="text-[13px] font-medium text-ink">{s.label}</span>
                <span className="ml-auto text-[12px] text-stone-400">{s.desc}</span>
              </div>
            ))}
          </div>
        </div>
      </Reveal>
    </div>
  )
}
