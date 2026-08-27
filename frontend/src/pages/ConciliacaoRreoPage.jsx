import { useState, useEffect } from 'react'
import { api } from '../lib/api'
import { PageHeader } from '../ui'
import ConciliacaoUpload from '../components/ConciliacaoUpload'
import ProcessingView from '../components/ProcessingView'
import RreoResult from '../components/RreoResult'

const LABELS = {
  rascunhoLabel: 'Rascunho MSC',
  rascunhoSub: 'Arquivo do RREO gerado pela MSC',
  homologadoLabel: 'SICONFI Homologado',
  homologadoSub: 'RREO exportado do SICONFI após transmissão',
  btn: 'Gerar conciliação RREO',
}

export default function ConciliacaoRreoPage() {
  const [step, setStep] = useState('upload')
  const [prefeituras, setPrefeituras] = useState([])
  const [selected, setSelected] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    api.get('/prefeituras?ativo=true')
      .then((r) => (r.ok ? r.json() : []))
      .then(setPrefeituras)
      .catch(() => {})
  }, [])

  async function process({ rascunho, homologado }) {
    setStep('processing')
    const form = new FormData()
    form.append('rascunho_msc', rascunho)
    form.append('siconfi_homologado', homologado)
    form.append('prefeitura_id', selected.id)
    try {
      const res = await api.upload('/conciliar-rreo', form)
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Erro no processamento' }))
        throw new Error(err.detail || 'Erro no processamento')
      }
      setResult(await res.json())
      setStep('result')
    } catch (e) {
      alert('Erro: ' + e.message)
      setStep('upload')
    }
  }

  function reset() {
    setResult(null)
    setSelected(null)
    setStep('upload')
  }

  return (
    <div>
      <PageHeader
        eyebrow="Conciliação · RREO"
        title="RREO × SICONFI"
        subtitle="Confronta todos os anexos do RREO com o arquivo homologado no SICONFI. Gera a planilha com as divergências destacadas e um relatório de auditoria com identidade Kora."
      />
      {step === 'upload' && (
        <ConciliacaoUpload
          prefeituras={prefeituras}
          selected={selected}
          onSelect={setSelected}
          onSubmit={process}
          labels={LABELS}
        />
      )}
      {step === 'processing' && (
        <ProcessingView
          title="Conciliando RREO…"
          steps={['Lendo MSC e SICONFI', 'Comparando anexo a anexo', 'Classificando divergências', 'Montando o relatório de auditoria']}
          note="A conciliação do RREO percorre todos os anexos — pode levar alguns segundos."
        />
      )}
      {step === 'result' && <RreoResult data={result} onReset={reset} />}
    </div>
  )
}
