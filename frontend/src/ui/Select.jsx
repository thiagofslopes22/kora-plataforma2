import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Check } from 'lucide-react'
import { cn } from '../lib/cn'

function useOutsideClose(ref, onClose) {
  useEffect(() => {
    function onDown(e) {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [ref, onClose])
}

// ── Single select ─────────────────────────────────────────────
export function Select({ value, onChange, options, placeholder = 'Selecione…', renderOption, className, disabled }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useOutsideClose(ref, () => setOpen(false))

  const selected = options.find((o) => o.value === value)

  return (
    <div ref={ref} className={cn('relative', className)}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'flex h-11 w-full items-center justify-between gap-2 rounded-xl border bg-surface px-3.5 text-sm shadow-soft',
          'transition-all duration-200 ease-expo focus-gold disabled:opacity-50',
          open ? 'border-gold shadow-focus' : 'border-stone-200 hover:border-stone-300',
        )}
      >
        <span className={cn('truncate', selected ? 'text-ink' : 'text-stone-400')}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown
          size={15}
          className={cn('shrink-0 text-stone-400 transition-transform duration-300 ease-expo', open && 'rotate-180')}
        />
      </button>

      {open && (
        <div className="absolute z-30 mt-2 max-h-72 w-full origin-top animate-scale-in overflow-auto rounded-2xl border border-stone-200 bg-surface p-1.5 shadow-lift">
          {options.length === 0 ? (
            <div className="px-3 py-4 text-center text-[13px] text-stone-400">Nenhuma opção</div>
          ) : (
            options.map((o) => {
              const active = o.value === value
              return (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => {
                    onChange(o.value, o)
                    setOpen(false)
                  }}
                  className={cn(
                    'flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-sm transition-colors duration-150',
                    active ? 'bg-gold-wash text-gold-deep' : 'text-stone-700 hover:bg-stone-100',
                  )}
                >
                  <span className="min-w-0 flex-1">{renderOption ? renderOption(o) : o.label}</span>
                  {active && <Check size={15} className="shrink-0 text-gold" />}
                </button>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}

// ── Multi select (checkbox list) ──────────────────────────────
export function MultiSelect({ values = [], onToggle, options, placeholder = 'Selecione…', className, emptyLabel }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useOutsideClose(ref, () => setOpen(false))

  const count = values.length

  return (
    <div ref={ref} className={cn('relative', className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'flex h-11 w-full items-center justify-between gap-2 rounded-xl border bg-surface px-3.5 text-sm shadow-soft',
          'transition-all duration-200 ease-expo focus-gold',
          open ? 'border-gold shadow-focus' : 'border-stone-200 hover:border-stone-300',
        )}
      >
        <span className={cn('truncate', count ? 'text-ink' : 'text-stone-400')}>
          {count === 0
            ? placeholder
            : count === 1
              ? options.find((o) => o.value === values[0])?.label
              : `${count} selecionadas`}
        </span>
        <ChevronDown
          size={15}
          className={cn('shrink-0 text-stone-400 transition-transform duration-300 ease-expo', open && 'rotate-180')}
        />
      </button>

      {open && (
        <div className="absolute z-30 mt-2 max-h-72 w-full origin-top animate-scale-in overflow-auto rounded-2xl border border-stone-200 bg-surface p-1.5 shadow-lift">
          {options.length === 0 ? (
            <div className="px-3 py-4 text-center text-[13px] text-stone-400">{emptyLabel || 'Nenhuma opção'}</div>
          ) : (
            options.map((o) => {
              const checked = values.includes(o.value)
              return (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => onToggle(o.value)}
                  className={cn(
                    'flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition-colors duration-150',
                    checked ? 'bg-gold-wash' : 'hover:bg-stone-100',
                  )}
                >
                  <span
                    className={cn(
                      'flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-md border transition-colors',
                      checked ? 'border-gold bg-gold text-white' : 'border-stone-300 bg-surface',
                    )}
                  >
                    {checked && <Check size={12} strokeWidth={3} />}
                  </span>
                  <span className="min-w-0 flex-1">{o.render ? o.render(o) : o.label}</span>
                </button>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
