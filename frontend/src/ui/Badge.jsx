import { cn } from '../lib/cn'

const TONES = {
  neutral: 'bg-stone-100 text-stone-600 ring-stone-200',
  gold:    'bg-gold-wash text-gold-deep ring-gold-ring',
  success: 'bg-success-bg text-success ring-success-ring',
  warning: 'bg-warning-bg text-warning ring-warning-ring',
  danger:  'bg-danger-bg text-danger ring-danger-ring',
  info:    'bg-info-bg text-info ring-info-ring',
  outline: 'bg-transparent text-stone-500 ring-stone-300',
}

export function Badge({ tone = 'neutral', icon: Icon, dot = false, className, children }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1 text-[11.5px] font-semibold tracking-tight ring-1 ring-inset',
        TONES[tone] || TONES.neutral,
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />}
      {Icon && <Icon size={12} strokeWidth={2} />}
      {children}
    </span>
  )
}
