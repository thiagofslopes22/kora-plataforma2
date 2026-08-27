import { cn } from '../lib/cn'

// Plain surface card — the workhorse for dense content (tables, forms).
export function Card({ className, children, hover = false, ...props }) {
  return (
    <div
      className={cn(
        'rounded-2xl border border-stone-200/80 bg-surface shadow-card',
        hover && 'transition-all duration-400 ease-expo hover:-translate-y-0.5 hover:shadow-lift',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}

// Double-bezel card — machined "glass plate in an aluminium tray" look
// for hero / feature surfaces. Outer shell + concentric inner core.
export function BezelCard({ className, coreClassName, children, hover = false, ...props }) {
  return (
    <div
      className={cn(
        'rounded-[1.75rem] border border-stone-200/70 bg-stone-100/60 p-1.5 shadow-card',
        'backdrop-saturate-150',
        hover && 'group transition-all duration-500 ease-expo hover:-translate-y-1 hover:shadow-lift',
        className,
      )}
      {...props}
    >
      <div
        className={cn(
          'rounded-core h-full bg-surface shadow-insetHi ring-1 ring-stone-200/60',
          coreClassName,
        )}
      >
        {children}
      </div>
    </div>
  )
}

export function CardHeader({ className, children, icon: Icon, action }) {
  return (
    <div className={cn('flex items-center gap-3 border-b border-stone-200/70 px-5 py-4', className)}>
      {Icon && (
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-stone-100 text-stone-500">
          <Icon size={16} strokeWidth={1.75} />
        </span>
      )}
      <div className="min-w-0 flex-1">{children}</div>
      {action}
    </div>
  )
}

export function CardTitle({ className, children, sub }) {
  return (
    <div className={className}>
      <h3 className="font-display text-[15px] font-semibold tracking-tight text-ink">{children}</h3>
      {sub && <p className="mt-0.5 text-[12.5px] text-stone-500">{sub}</p>}
    </div>
  )
}
