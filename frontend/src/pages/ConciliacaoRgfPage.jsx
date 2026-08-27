import { useState, useEffect } from 'react'
import { api } from '../lib/api'
import { PageHeader } from '../ui'
import ConciliacaoUpload from '../components/ConciliacaoUpload'
import ProcessingView from '../components/ProcessingView'
import RgfResult from '../components/RgfResult'

const LABELS = {
  rascunhoLabel: 'Rascunho MSC',
  rascunhoSub: 'Arquivo gerado pelo sistema da prefeitura',
  homologadoLabel: 'SICONFI Homologado',
  homologadoSub: 'Arquivo exportado do SICONFI após transmissão',
  btn: 'Gerar planilha conciliada',
}

export default function ConciliacaoRgfPage() {
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
    form.append('rascunho', rascunho)
    form.append('homologado', homologado)
    form.append('prefeitura_id', selected.id)
    try {
      const res = await api.upload('/conciliar', form)
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
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
        eyebrow="Conciliação · RGF"
        title="MSC × SICONFI"
        subtitle="Envie o rascunho gerado pela MSC e o arquivo homologado no SICONFI. O sistema compara todas as células e devolve uma planilha com as divergências marcadas no layout original."
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
          title="Conciliando RGF…"
          steps={['Lendo os dois arquivos', 'Comparando célula a célula', 'Classificando divergências', 'Gerando a planilha']}
        />
      )}
      {step === 'result' && <RgfResult data={result} onReset={reset} />}
    </div>
  )
}
