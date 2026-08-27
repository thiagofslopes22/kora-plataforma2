import { cn } from '../lib/cn'

// ── Eyebrow micro-tag ─────────────────────────────────────────
export function Eyebrow({ className, children, dot = true }) {
  return (
    <span className={cn('eyebrow', className)}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-gold" />}
      {children}
    </span>
  )
}

// ── Page header ───────────────────────────────────────────────
export function PageHeader({ eyebrow, title, subtitle, actions, className }) {
  return (
    <div className={cn('mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between', className)}>
      <div className="min-w-0">
        {eyebrow && <Eyebrow className="mb-3">{eyebrow}</Eyebrow>}
        <h1 className="font-display text-[30px] font-semibold leading-[1.05] tracking-tighter text-ink sm:text-[38px]">
          {title}
        </h1>
        {subtitle && <p className="mt-2 max-w-2xl text-[14.5px] leading-relaxed text-stone-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2.5">{actions}</div>}
    </div>
  )
}

// ── Field wrapper ─────────────────────────────────────────────
export function Field({ label, required, hint, error, children, className }) {
  return (
    <label className={cn('flex flex-col gap-1.5', className)}>
      {label && (
        <span className="flex items-center gap-1 text-[12.5px] font-semibold tracking-tight text-stone-600">
          {label}
          {required && <span className="text-danger">*</span>}
        </span>
      )}
      {children}
      {hint && !error && <span className="text-[12px] text-stone-400">{hint}</span>}
      {error && <span className="text-[12px] font-medium text-danger">{error}</span>}
    </label>
  )
}

// ── Input ─────────────────────────────────────────────────────
export function Input({ className, ...props }) {
  return (
    <input
      className={cn(
        'h-11 w-full rounded-xl border border-stone-200 bg-surface px-3.5 text-sm text-ink',
        'placeholder:text-stone-400 shadow-soft transition-all duration-200 ease-expo',
        'hover:border-stone-300 focus:border-gold focus:shadow-focus focus:outline-none',
        className,
      )}
      {...props}
    />
  )
}

// ── Spinner ───────────────────────────────────────────────────
export function Spinner({ size = 18, className }) {
  return (
    <span
      className={cn('inline-block animate-spin-slow rounded-full border-2 border-current border-t-transparent', className)}
      style={{ width: size, height: size }}
    />
  )
}

// ── Reveal wrapper (scroll-in with stagger) ───────────────────
export function Reveal({ as: Tag = 'div', delay = 0, className, children, ...props }) {
  return (
    <Tag
      className={cn('reveal', className)}
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
      {...props}
    >
      {children}
    </Tag>
  )
}

// ── Empty state ───────────────────────────────────────────────
export function EmptyState({ icon: Icon, title, children, action, className }) {
  return (
    <div className={cn('flex flex-col items-center gap-3 px-6 py-14 text-center', className)}>
      {Icon && (
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-stone-100 text-stone-300">
          <Icon size={26} strokeWidth={1.5} />
        </span>
      )}
      {title && <p className="font-display text-[15px] font-semibold text-ink">{title}</p>}
      {children && <p className="max-w-sm text-[13.5px] leading-relaxed text-stone-500">{children}</p>}
      {action}
    </div>
  )
}
