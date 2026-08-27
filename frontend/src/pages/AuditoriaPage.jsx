import { useState, useEffect, useMemo } from 'react'
import {
  FileDown, Sparkles, FileText, ChevronDown, CheckCircle2, Circle,
  ExternalLink, AlertCircle, Layers, ScanSearch,
} from 'lucide-react'
import { auditorApi } from '../lib/apiAuditor'
import { triggerDownload } from '../lib/api'
import { cn } from '../lib/cn'
import { PageHeader, Eyebrow, Badge, Spinner, Reveal } from '../ui'
import { FileSlot, FileDrop } from '../components/FileDrop'
import AuditResult from '../components/AuditResult'
import { useReveal } from '../hooks/useReveal'

const DOCS = [
  { key: 'anx_10_atual',    code: 'ANX_10_ATUAL',    label: 'Anexo 10 — Receita (Atual)',       badge: 'PyMuPDF', kind: 'pdf' },
  { key: 'anx_10_anterior', code: 'ANX_10_ANTERIOR', label: 'Anexo 10 — Receita (Anterior)',    badge: 'PyMuPDF', kind: 'pdf' },
  { key: 'anx_12',          code: 'ANX_12',          label: 'Anexo 12 — Balanço Orçamentário',  badge: 'Camelot', kind: 'pdf' },
  { key: 'anx_06',          code: 'ANX_06',          label: 'Anexo 06 — Programa de Trabalho',  badge: 'PyMuPDF', kind: 'pdf' },
  { key: 'anx_02',          code: 'ANX_02',          label: 'Anexo 02 — Natureza da Despesa',   badge: 'PyMuPDF', kind: 'pdf' },
  { key: 'anx_13',          code: 'ANX_13',          label: 'Anexo 13 — Balanço Financeiro',    badge: 'PyMuPDF', kind: 'pdf' },
  { key: 'anx_14',          code: 'ANX_14',          label: 'Anexo 14 — Balanço Patrimonial',   badge: 'PyMuPDF', kind: 'pdf' },
  { key: 'dfc',             code: 'DFC',             label: 'DFC — Fluxos de Caixa',            badge: 'PyMuPDF', kind: 'pdf' },
  { key: 'loa',             code: 'LOA',             label: 'LOA — Lei Orçamentária Anual',     badge: 'PyMuPDF', kind: 'pdf' },
  { key: 'rgf2semestre',    code: 'RGF_2SEM',        label: 'RGF 2º Semestre — Pessoal',        badge: 'PyMuPDF', kind: 'pdf' },
  { key: 'rgf1semestre',    code: 'RGF_1SEM',        label: 'RGF 1º Semestre — Pessoal',        badge: 'PyMuPDF', kind: 'pdf' },
  { key: 'bo_fundeb',       code: 'BO_FUNDEB',       label: 'Balanço Orçamentário — FUNDEB',    badge: 'PyMuPDF', kind: 'pdf' },
  { key: 'ff_saude',        code: 'FF_SAUDE',        label: 'Fundo a Fundo — Saúde (FNS)',      badge: 'Excel',   kind: 'xls' },
]

export default function AuditoriaPage() {
  const ref = useReveal([])
  const [files, setFiles] = useState({}) // key → File
  const [quadros, setQuadros] = useState([])
  const [showQuadros, setShowQuadros] = useState(false)

  const [busy, setBusy] = useState('') // 'gerar' | 'auditar'
  const [error, setError] = useState('')
  const [auditResult, setAuditResult] = useState(null)
  const [gerarInfo, setGerarInfo] = useState(null) // {tabelas, municipio}

  // Passo 2
  const [excel, setExcel] = useState(null)
  const [ritBusy, setRitBusy] = useState(false)
  const [ritStatus, setRitStatus] = useState(null) // {type, url?, msg}

  useEffect(() => {
    auditorApi.getJson('/quadros').then(setQuadros).catch(() => {})
  }, [])

  const count = Object.keys(files).length
  const selectedCodes = useMemo(() => new Set(DOCS.filter((d) => files[d.key]).map((d) => d.code)), [files])

  const quadrosStatus = useMemo(() => {
    return quadros.map((q) => {
      const faltando = (q.docs_necessarios || []).filter((c) => !selectedCodes.has(c))
      const ready = q.implementado && faltando.length === 0
      return { ...q, faltando, ready }
    })
  }, [quadros, selectedCodes])

  const readyCount = quadrosStatus.filter((q) => q.ready).length
  const totalImpl = quadrosStatus.filter((q) => q.implementado).length || quadros.length

  function setFile(key, file) {
    setFiles((f) => ({ ...f, [key]: file }))
    setError('')
  }
  function clearFile(key) {
    setFiles((f) => {
      const n = { ...f }
      delete n[key]
      return n
    })
  }

  function buildForm() {
    const form = new FormData()
    DOCS.forEach((d) => {
      if (files[d.key]) form.append(d.key, files[d.key])
    })
    return form
  }

  async function handleGerar() {
    if (count === 0) return setError('Selecione pelo menos um documento.')
    setBusy('gerar')
    setError('')
    setGerarInfo(null)
    try {
      const res = await auditorApi.postFormRaw('/gerar', buildForm())
      const tabelas = res.headers.get('X-Tabelas-Geradas') || '?'
      const municipio = res.headers.get('X-Municipio') || ''
      const blob = await res.blob()
      triggerDownload(blob, `Kora_Trabalho_${municipio || 'planilha'}.xlsx`)
      setGerarInfo({ tabelas, municipio })
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  async function handleAuditar() {
    if (count === 0) return setError('Selecione pelo menos um documento.')
    setBusy('auditar')
    setError('')
    setAuditResult(null)
    try {
      const data = await auditorApi.postForm('/auditar', buildForm())
      setAuditResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  async function handleRelatorio() {
    if (!excel) return setRitStatus({ type: 'error', msg: 'Selecione o Excel preenchido.' })
    setRitBusy(true)
    setRitStatus(null)
    try {
      const form = new FormData()
      form.append('excel', excel)
      const res = await auditorApi.postFormRaw('/relatorio', form)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const win = window.open(url, '_blank')
      setRitStatus({
        type: 'ok',
        url,
        msg: win ? 'Relatório RIT gerado — abrimos em uma nova aba.' : 'Relatório gerado, mas o navegador bloqueou a nova aba.',
      })
    } catch (e) {
      setRitStatus({ type: 'error', msg: e.message })
    } finally {
      setRitBusy(false)
    }
  }

  const anyBusy = !!busy

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="Motor de auditoria"
        title="Auditoria RIT"
        subtitle="Envie os anexos do balanço em PDF. O Kora extrai os quadros contábeis, gera a planilha de trabalho e produz o relatório de inspeção (RIT) com apoio de IA."
      />

      {/* ── Passo 1 ── */}
      <Reveal className="overflow-hidden rounded-[1.75rem] border border-stone-200/70 bg-stone-100/50 p-1.5 shadow-card">
        <div className="rounded-core bg-surface">
          <div className="flex items-center gap-3 border-b border-stone-200/70 px-6 py-4">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gold-wash text-gold">
              <Layers size={17} strokeWidth={1.75} />
            </span>
            <div className="flex-1">
              <p className="font-mono text-[10.5px] font-semibold uppercase tracking-eyebrow text-stone-400">Passo 1</p>
              <h3 className="font-display text-[16px] font-semibold tracking-tight text-ink">Anexos do balanço</h3>
            </div>
            <Badge tone={count > 0 ? 'gold' : 'neutral'}>{count} de {DOCS.length}</Badge>
          </div>

          <div className="p-5 sm:p-6">
            {/* Grid of slots */}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {DOCS.map((d) => (
                <FileSlot
                  key={d.key}
                  label={d.label}
                  badge={d.badge}
                  kind={d.kind}
                  file={files[d.key] || null}
                  onFile={(f) => setFile(d.key, f)}
                  onClear={() => clearFile(d.key)}
                />
              ))}
            </div>

            {/* Quadros availability */}
            {quadros.length > 0 && (
              <div className="mt-5 overflow-hidden rounded-2xl border border-stone-200/70 bg-stone-50">
                <button
                  onClick={() => setShowQuadros((s) => !s)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left"
                >
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface text-gold shadow-soft">
                    <ScanSearch size={15} strokeWidth={1.75} />
                  </span>
                  <div className="flex-1">
                    <p className="text-[13px] font-semibold tracking-tight text-ink">
                      {readyCount} de {totalImpl} quadros prontos
                    </p>
                    <p className="text-[12px] text-stone-500">com os documentos selecionados</p>
                  </div>
                  <div className="hidden h-1.5 w-28 overflow-hidden rounded-full bg-stone-200 sm:block">
                    <div className="h-full rounded-full bg-gold transition-all duration-500 ease-expo" style={{ width: `${totalImpl ? (readyCount / totalImpl) * 100 : 0}%` }} />
                  </div>
                  <ChevronDown size={16} className={cn('text-stone-400 transition-transform duration-300 ease-expo', showQuadros && 'rotate-180')} />
                </button>

                {showQuadros && (
                  <div className="grid gap-1.5 border-t border-stone-200/70 p-3 sm:grid-cols-2 lg:grid-cols-3">
                    {quadrosStatus.filter((q) => q.implementado).map((q) => (
                      <div key={q.chave} className={cn('flex items-center gap-2 rounded-xl px-2.5 py-2 text-[12px]', q.ready ? 'bg-success-bg/60' : 'bg-surface')}>
                        {q.ready
                          ? <CheckCircle2 size={14} className="shrink-0 text-success" />
                          : <Circle size={14} className="shrink-0 text-stone-300" />}
                        <span className="font-mono text-[10.5px] font-semibold text-stone-400">{q.chave.replace('quadro_', 'Q')}</span>
                        <span className={cn('truncate', q.ready ? 'font-medium text-ink' : 'text-stone-400')}>{q.descricao}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {error && (
              <div className="mt-5 flex items-center gap-2 rounded-xl border border-danger-ring bg-danger-bg px-3.5 py-2.5 text-[13px] font-medium text-danger animate-scale-in">
                <AlertCircle size={15} className="shrink-0" /> {error}
              </div>
            )}

            {gerarInfo && (
              <div className="mt-5 flex items-center gap-2 rounded-xl border border-success-ring bg-success-bg px-3.5 py-2.5 text-[13px] font-medium text-success animate-scale-in">
                <CheckCircle2 size={15} className="shrink-0" />
                Planilha gerada — {gerarInfo.tabelas} quadro(s){gerarInfo.municipio && ` · ${gerarInfo.municipio}`}. Preencha a aba “Dados Manuais” e volte no Passo 2.
              </div>
            )}

            {/* Actions */}
            <div className="mt-6 flex flex-col gap-3 sm:flex-row">
              <button
                onClick={handleGerar}
                disabled={anyBusy || count === 0}
                className="group flex h-[52px] flex-1 items-center justify-center gap-2.5 rounded-pill bg-gold pl-6 pr-3 font-semibold text-white shadow-[0_1px_2px_rgba(90,71,14,0.35),0_14px_30px_-10px_rgba(156,122,22,0.7)] transition-all duration-300 ease-expo hover:bg-gold-hover active:scale-[0.99] disabled:pointer-events-none disabled:opacity-40"
              >
                {busy === 'gerar' ? <Spinner size={17} className="text-white" /> : null}
                <span>{busy === 'gerar' ? 'Gerando planilha…' : 'Gerar planilha de trabalho'}</span>
                {busy !== 'gerar' && (
                  <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/15 transition-transform duration-300 ease-expo group-hover:translate-x-0.5 group-hover:scale-105">
                    <FileDown size={17} />
                  </span>
                )}
              </button>
              <button
                onClick={handleAuditar}
                disabled={anyBusy || count === 0}
                className="group flex h-[52px] items-center justify-center gap-2.5 rounded-pill bg-ink px-6 font-semibold text-white shadow-[0_1px_2px_rgba(0,0,0,0.3),0_14px_30px_-12px_rgba(0,0,0,0.6)] transition-all duration-300 ease-expo hover:bg-stone-800 active:scale-[0.99] disabled:pointer-events-none disabled:opacity-40"
              >
                {busy === 'auditar' ? <Spinner size={17} className="text-white" /> : <Sparkles size={17} className="text-gold" />}
                <span>{busy === 'auditar' ? 'Analisando…' : 'Auditar com IA'}</span>
              </button>
            </div>
            <p className="mt-3 text-[12px] leading-relaxed text-stone-400">
              <strong className="font-semibold text-stone-500">Gerar planilha</strong> extrai os dados e baixa o Excel de trabalho.{' '}
              <strong className="font-semibold text-stone-500">Auditar com IA</strong> analisa os quadros e aponta inconformidades com base legal.
            </p>
          </div>
        </div>
      </Reveal>

      {/* AI results */}
      {auditResult && <AuditResult data={auditResult} />}

      {/* ── Passo 2 ── */}
      <Reveal delay={80} className="mt-6 overflow-hidden rounded-[1.75rem] border border-stone-200/70 bg-stone-100/50 p-1.5 shadow-card">
        <div className="rounded-core bg-surface">
          <div className="flex items-center gap-3 border-b border-stone-200/70 px-6 py-4">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gold-wash text-gold">
              <FileText size={17} strokeWidth={1.75} />
            </span>
            <div className="flex-1">
              <p className="font-mono text-[10.5px] font-semibold uppercase tracking-eyebrow text-stone-400">Passo 2</p>
              <h3 className="font-display text-[16px] font-semibold tracking-tight text-ink">Relatório de inspeção (RIT)</h3>
            </div>
          </div>

          <div className="p-5 sm:p-6">
            <p className="mb-4 text-[13.5px] leading-relaxed text-stone-500">
              Abra a planilha gerada no Passo 1, preencha a aba <strong className="font-semibold text-ink">“Dados Manuais”</strong> e reenvie aqui.
              O Kora aciona a IA para redigir as ocorrências e produz o relatório RIT em HTML.
            </p>

            <div className="max-w-xl">
              <FileDrop
                label="Excel preenchido"
                subtitle="Planilha do Passo 1 com a aba “Dados Manuais” preenchida"
                kind="xls"
                file={excel}
                onFile={setExcel}
                onClear={() => setExcel(null)}
              />
            </div>

            {ritStatus && (
              <div
                className={cn(
                  'mt-4 flex items-center gap-2 rounded-xl px-3.5 py-2.5 text-[13px] font-medium animate-scale-in',
                  ritStatus.type === 'ok' ? 'border border-success-ring bg-success-bg text-success' : 'border border-danger-ring bg-danger-bg text-danger',
                )}
              >
                {ritStatus.type === 'ok' ? <CheckCircle2 size={15} className="shrink-0" /> : <AlertCircle size={15} className="shrink-0" />}
                <span className="flex-1">{ritStatus.msg}</span>
                {ritStatus.url && (
                  <a href={ritStatus.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-semibold underline">
                    Abrir <ExternalLink size={13} />
                  </a>
                )}
              </div>
            )}

            <button
              onClick={handleRelatorio}
              disabled={ritBusy || !excel}
              className="group mt-6 flex h-[52px] items-center justify-center gap-2.5 rounded-pill bg-gold pl-6 pr-3 font-semibold text-white shadow-[0_1px_2px_rgba(90,71,14,0.35),0_14px_30px_-10px_rgba(156,122,22,0.7)] transition-all duration-300 ease-expo hover:bg-gold-hover active:scale-[0.99] disabled:pointer-events-none disabled:opacity-40"
            >
              {ritBusy ? <Spinner size={17} className="text-white" /> : null}
              <span>{ritBusy ? 'Gerando RIT… (a IA está redigindo)' : 'Gerar relatório RIT'}</span>
              {!ritBusy && (
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/15 transition-transform duration-300 ease-expo group-hover:translate-x-0.5 group-hover:scale-105">
                  <ExternalLink size={16} />
                </span>
              )}
            </button>
          </div>
        </div>
      </Reveal>
    </div>
  )
}
