import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  Building2, Plus, Pencil, Power, Trash2, X, AlertCircle, CheckCircle2, ArrowUpRight,
} from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../contexts/AuthContext'
import { cn } from '../lib/cn'
import { PageHeader, Badge, Spinner, EmptyState, Field, Input, Reveal } from '../ui'
import { useReveal } from '../hooks/useReveal'

const EMPTY = { nome: '', municipio: '', uf: '' }

export default function MunicipiosPage() {
  const { isAdmin } = useAuth()
  const ref = useReveal([])
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)

  const [form, setForm] = useState(EMPTY)
  const [editId, setEditId] = useState(null)
  const [formError, setFormError] = useState('')
  const [formOk, setFormOk] = useState('')
  const [saving, setSaving] = useState(false)
  const [togglingId, setTogglingId] = useState(null)
  const [confirmId, setConfirmId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)

  async function fetchItems() {
    setLoading(true)
    try {
      const res = await api.get('/prefeituras')
      if (res.ok) setItems(await res.json())
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { fetchItems() }, [])

  function startEdit(p) {
    setEditId(p.id)
    setForm({ nome: p.nome, municipio: p.municipio, uf: p.uf })
    setFormError(''); setFormOk('')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  function cancelEdit() {
    setEditId(null); setForm(EMPTY); setFormError(''); setFormOk('')
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setFormError(''); setFormOk(''); setSaving(true)
    try {
      const body = { nome: form.nome.trim(), municipio: form.municipio.trim(), uf: form.uf.trim().toUpperCase() }
      const res = editId ? await api.put(`/prefeituras/${editId}`, body) : await api.post('/prefeituras', body)
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'Erro ao salvar')
      }
      setFormOk(editId ? 'Município atualizado.' : 'Município cadastrado.')
      cancelEdit()
      await fetchItems()
    } catch (e) {
      setFormError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function toggle(p) {
    setTogglingId(p.id)
    try {
      const res = await api.patch(`/prefeituras/${p.id}/toggle`)
      if (res.ok) await fetchItems()
    } finally {
      setTogglingId(null)
    }
  }

  async function remove(id) {
    setDeletingId(id)
    try {
      const res = await api.delete(`/prefeituras/${id}`)
      if (res.ok || res.status === 204) {
        setConfirmId(null)
        await fetchItems()
      } else {
        const data = await res.json().catch(() => ({}))
        setFormError(data.detail || 'Erro ao excluir.')
        setConfirmId(null)
      }
    } catch {
      setFormError('Erro de conexão ao excluir.')
      setConfirmId(null)
    } finally {
      setDeletingId(null)
    }
  }

  const valid = form.nome.trim() && form.municipio.trim() && form.uf.trim().length === 2

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="Cadastros"
        title="Municípios"
        subtitle={isAdmin ? 'Gerencie as prefeituras monitoradas pela plataforma.' : 'Prefeituras às quais você tem acesso.'}
        actions={<Badge tone="neutral">{items.length} {items.length === 1 ? 'município' : 'municípios'}</Badge>}
      />

      {/* Admin form */}
      {isAdmin && (
        <Reveal className="mb-6 overflow-hidden rounded-3xl border border-stone-200/80 bg-surface shadow-card">
          <div className="flex items-center gap-3 border-b border-stone-200/70 px-6 py-4">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gold-wash text-gold">
              {editId ? <Pencil size={16} strokeWidth={1.75} /> : <Plus size={16} strokeWidth={1.75} />}
            </span>
            <h3 className="flex-1 font-display text-[15px] font-semibold tracking-tight text-ink">
              {editId ? 'Editar município' : 'Novo município'}
            </h3>
            {editId && (
              <button onClick={cancelEdit} className="flex h-8 w-8 items-center justify-center rounded-full text-stone-400 hover:bg-stone-100 hover:text-ink" title="Cancelar">
                <X size={15} />
              </button>
            )}
          </div>
          <form onSubmit={handleSubmit} className="p-6">
            <div className="grid gap-4 sm:grid-cols-[1.4fr_1.4fr_auto]">
              <Field label="Nome da prefeitura" required>
                <Input value={form.nome} onChange={(e) => setForm((f) => ({ ...f, nome: e.target.value }))} placeholder="Ex.: Prefeitura Municipal de Paço do Lumiar" />
              </Field>
              <Field label="Município" required>
                <Input value={form.municipio} onChange={(e) => setForm((f) => ({ ...f, municipio: e.target.value }))} placeholder="Ex.: Paço do Lumiar" />
              </Field>
              <Field label="UF" required className="w-24">
                <Input value={form.uf} onChange={(e) => setForm((f) => ({ ...f, uf: e.target.value.slice(0, 2).toUpperCase() }))} placeholder="MA" maxLength={2} className="uppercase" />
              </Field>
            </div>

            {formError && (
              <div className="mt-4 flex items-center gap-2 text-[13px] font-medium text-danger">
                <AlertCircle size={14} /> {formError}
              </div>
            )}
            {formOk && (
              <div className="mt-4 flex items-center gap-2 text-[13px] font-medium text-success">
                <CheckCircle2 size={14} /> {formOk}
              </div>
            )}

            <button
              type="submit"
              disabled={saving || !valid}
              className="mt-5 inline-flex h-11 items-center gap-2 rounded-pill bg-gold px-6 text-sm font-semibold text-white shadow-[0_1px_2px_rgba(90,71,14,0.35),0_10px_24px_-10px_rgba(156,122,22,0.7)] transition-all duration-300 ease-expo hover:bg-gold-hover active:scale-[0.98] disabled:opacity-40"
            >
              {saving && <Spinner size={15} className="text-white" />}
              {saving ? 'Salvando…' : editId ? 'Salvar alterações' : 'Cadastrar município'}
            </button>
          </form>
        </Reveal>
      )}

      {/* List */}
      <Reveal delay={60} className="overflow-hidden rounded-3xl border border-stone-200/80 bg-surface shadow-card">
        {loading ? (
          <div className="flex items-center justify-center py-16 text-gold"><Spinner size={22} /></div>
        ) : items.length === 0 ? (
          <EmptyState icon={Building2} title="Nenhum município cadastrado">
            {isAdmin ? 'Use o formulário acima para cadastrar o primeiro.' : 'Você ainda não está vinculado a nenhuma prefeitura.'}
          </EmptyState>
        ) : (
          <div className="divide-y divide-stone-200/70">
            {items.map((p) => (
              <div key={p.id} className={cn('group flex items-center gap-4 px-5 py-4 transition-colors hover:bg-stone-50', !p.ativo && 'opacity-60')}>
                <Link to={`/municipios/${p.id}`} className="flex min-w-0 flex-1 items-center gap-4">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-stone-100 text-stone-500 transition-colors group-hover:bg-gold-wash group-hover:text-gold">
                    <Building2 size={19} strokeWidth={1.6} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[14.5px] font-semibold tracking-tight text-ink">{p.municipio}</p>
                    <p className="truncate text-[12.5px] text-stone-400">{p.nome}</p>
                  </div>
                  <span className="hidden shrink-0 rounded-pill bg-stone-100 px-2.5 py-1 font-mono text-[11px] font-semibold text-stone-500 sm:inline">{p.uf}</span>
                  <Badge tone={p.ativo ? 'success' : 'neutral'} dot>{p.ativo ? 'Ativo' : 'Inativo'}</Badge>
                </Link>

                {isAdmin ? (
                  <div className="flex shrink-0 items-center gap-1">
                    <button onClick={() => startEdit(p)} title="Editar" className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-ink">
                      <Pencil size={14} />
                    </button>
                    <button onClick={() => toggle(p)} disabled={togglingId === p.id} title={p.ativo ? 'Desativar' : 'Reativar'} className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-stone-100 hover:text-warning">
                      <Power size={14} />
                    </button>
                    {confirmId === p.id ? (
                      <span className="flex items-center gap-1 rounded-lg bg-danger-bg px-1.5 py-1">
                        <button onClick={() => remove(p.id)} disabled={deletingId === p.id} title="Confirmar" className="flex h-6 w-6 items-center justify-center rounded-md text-danger hover:bg-white">
                          {deletingId === p.id ? <Spinner size={12} /> : <Trash2 size={13} />}
                        </button>
                        <button onClick={() => setConfirmId(null)} title="Cancelar" className="flex h-6 w-6 items-center justify-center rounded-md text-stone-500 hover:bg-white">
                          <X size={13} />
                        </button>
                      </span>
                    ) : (
                      <button onClick={() => setConfirmId(p.id)} title="Excluir" className="flex h-8 w-8 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-danger-bg hover:text-danger">
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                ) : (
                  <Link to={`/municipios/${p.id}`} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-stone-300 transition-colors hover:text-gold">
                    <ArrowUpRight size={16} />
                  </Link>
                )}
              </div>
            ))}
          </div>
        )}
      </Reveal>
    </div>
  )
}
