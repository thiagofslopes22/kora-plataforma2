import { useState, useEffect } from 'react'
import { UserPlus, Power, Shield, User, AlertCircle, Building2, CheckCircle2 } from 'lucide-react'
import { api } from '../lib/api'
import { cn } from '../lib/cn'
import { PageHeader, Badge, Spinner, Field, Input, Select, MultiSelect, Reveal } from '../ui'
import { useReveal } from '../hooks/useReveal'

const EMPTY = { nome: '', email: '', senha: '', role: 'auditor', prefeitura_ids: [] }

const ROLE_OPTS = [
  { value: 'auditor', label: 'Auditor' },
  { value: 'admin', label: 'Administrador' },
]

export default function UsuariosPage() {
  const ref = useReveal([])
  const [users, setUsers] = useState([])
  const [prefeituras, setPrefeituras] = useState([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState(EMPTY)
  const [formError, setFormError] = useState('')
  const [formOk, setFormOk] = useState('')
  const [saving, setSaving] = useState(false)
  const [togglingId, setTogglingId] = useState(null)

  async function fetchUsers() {
    setLoading(true)
    try {
      const res = await api.get('/auth/usuarios')
      if (res.ok) setUsers(await res.json())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchUsers()
    api.get('/prefeituras').then((r) => (r.ok ? r.json() : [])).then(setPrefeituras).catch(() => {})
  }, [])

  function togglePref(id) {
    setForm((f) => ({
      ...f,
      prefeitura_ids: f.prefeitura_ids.includes(id)
        ? f.prefeitura_ids.filter((x) => x !== id)
        : [...f.prefeitura_ids, id],
    }))
  }

  async function handleCreate(e) {
    e.preventDefault()
    setFormError(''); setFormOk(''); setSaving(true)
    try {
      const payload = {
        nome: form.nome, email: form.email, senha: form.senha, role: form.role,
        prefeitura_ids: form.role === 'auditor' ? form.prefeitura_ids : [],
      }
      const res = await api.post('/auth/usuarios', payload)
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'Erro ao criar usuário')
      }
      setForm(EMPTY)
      setFormOk('Usuário criado com sucesso.')
      await fetchUsers()
    } catch (e) {
      setFormError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function toggle(u) {
    setTogglingId(u.id)
    try {
      await api.patch(`/auth/usuarios/${u.id}/toggle`)
      await fetchUsers()
    } finally {
      setTogglingId(null)
    }
  }

  const prefOptions = prefeituras.map((p) => ({ value: p.id, label: `${p.municipio} · ${p.uf}` }))
  const valid = form.nome.trim() && form.email.trim() && form.senha.trim() &&
    (form.role !== 'auditor' || form.prefeitura_ids.length > 0)

  return (
    <div ref={ref}>
      <PageHeader
        eyebrow="Cadastros"
        title="Usuários"
        subtitle="Gerencie quem tem acesso à plataforma e a quais municípios."
        actions={<Badge tone="neutral">{users.length} {users.length === 1 ? 'usuário' : 'usuários'}</Badge>}
      />

      {/* Create form */}
      <Reveal className="mb-6 overflow-hidden rounded-3xl border border-stone-200/80 bg-surface shadow-card">
        <div className="flex items-center gap-3 border-b border-stone-200/70 px-6 py-4">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gold-wash text-gold">
            <UserPlus size={16} strokeWidth={1.75} />
          </span>
          <h3 className="font-display text-[15px] font-semibold tracking-tight text-ink">Adicionar usuário</h3>
        </div>
        <form onSubmit={handleCreate} className="p-6">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Field label="Nome" required>
              <Input value={form.nome} onChange={(e) => setForm((f) => ({ ...f, nome: e.target.value }))} placeholder="Nome completo" />
            </Field>
            <Field label="E-mail" required>
              <Input type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} placeholder="usuario@email.com" />
            </Field>
            <Field label="Senha" required>
              <Input type="password" value={form.senha} onChange={(e) => setForm((f) => ({ ...f, senha: e.target.value }))} placeholder="••••••••" />
            </Field>
            <Field label="Perfil" required>
              <Select
                value={form.role}
                onChange={(v) => setForm((f) => ({ ...f, role: v, prefeitura_ids: [] }))}
                options={ROLE_OPTS}
              />
            </Field>
          </div>

          {form.role === 'auditor' && (
            <div className="mt-4 max-w-md">
              <Field label="Municípios vinculados" required hint="O auditor só enxerga os municípios selecionados.">
                <MultiSelect
                  values={form.prefeitura_ids}
                  onToggle={togglePref}
                  options={prefOptions}
                  placeholder="Selecionar municípios…"
                  emptyLabel="Nenhum município cadastrado"
                />
              </Field>
              {form.prefeitura_ids.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {form.prefeitura_ids.map((pid) => {
                    const p = prefeituras.find((x) => x.id === pid)
                    if (!p) return null
                    return (
                      <span key={pid} className="inline-flex items-center gap-1.5 rounded-pill bg-gold-wash px-2.5 py-1 text-[12px] font-medium text-gold-deep">
                        <Building2 size={11} /> {p.municipio}
                      </span>
                    )
                  })}
                </div>
              )}
            </div>
          )}

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
            {saving ? 'Criando…' : 'Criar usuário'}
          </button>
        </form>
      </Reveal>

      {/* Users list */}
      <Reveal delay={60} className="overflow-hidden rounded-3xl border border-stone-200/80 bg-surface shadow-card">
        <div className="flex items-center gap-3 border-b border-stone-200/70 px-6 py-4">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-stone-100 text-stone-500">
            <User size={16} strokeWidth={1.75} />
          </span>
          <h3 className="flex-1 font-display text-[15px] font-semibold tracking-tight text-ink">Usuários cadastrados</h3>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 text-gold"><Spinner size={22} /></div>
        ) : (
          <div className="divide-y divide-stone-200/70">
            {users.map((u) => (
              <div key={u.id} className={cn('flex flex-wrap items-center gap-4 px-5 py-4 transition-colors hover:bg-stone-50', !u.ativo && 'opacity-60')}>
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ink text-[14px] font-semibold text-white">
                  {u.nome?.[0]?.toUpperCase() || 'U'}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-semibold tracking-tight text-ink">{u.nome}</p>
                  <p className="truncate text-[12.5px] text-stone-400">{u.email}</p>
                </div>

                <Badge tone={u.role === 'admin' ? 'gold' : 'neutral'} icon={u.role === 'admin' ? Shield : User}>
                  {u.role === 'admin' ? 'Administrador' : 'Auditor'}
                </Badge>

                <div className="hidden min-w-0 max-w-xs flex-wrap gap-1 lg:flex">
                  {u.prefeituras && u.prefeituras.length > 0 ? (
                    u.prefeituras.slice(0, 3).map((p) => (
                      <span key={p.id} className="rounded-pill bg-stone-100 px-2 py-0.5 text-[11px] font-medium text-stone-500">
                        {p.nome} <span className="text-stone-400">{p.uf}</span>
                      </span>
                    ))
                  ) : (
                    <span className="text-[12px] text-stone-300">—</span>
                  )}
                  {u.prefeituras && u.prefeituras.length > 3 && (
                    <span className="rounded-pill bg-stone-100 px-2 py-0.5 text-[11px] font-medium text-stone-400">+{u.prefeituras.length - 3}</span>
                  )}
                </div>

                <Badge tone={u.ativo ? 'success' : 'neutral'} dot>{u.ativo ? 'Ativo' : 'Inativo'}</Badge>

                <button
                  onClick={() => toggle(u)}
                  disabled={togglingId === u.id}
                  title={u.ativo ? 'Desativar' : 'Ativar'}
                  className={cn(
                    'flex h-9 items-center gap-1.5 rounded-pill border px-3 text-[12.5px] font-semibold transition-colors',
                    u.ativo ? 'border-stone-200 text-stone-500 hover:border-danger-ring hover:text-danger' : 'border-success-ring text-success hover:bg-success-bg',
                  )}
                >
                  {togglingId === u.id ? <Spinner size={13} /> : <Power size={13} />}
                  {u.ativo ? 'Desativar' : 'Ativar'}
                </button>
              </div>
            ))}
          </div>
        )}
      </Reveal>
    </div>
  )
}
