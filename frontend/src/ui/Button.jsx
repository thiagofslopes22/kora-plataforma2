import { forwardRef } from 'react'
import { cn } from '../lib/cn'

const VARIANTS = {
  primary:
    'bg-gold text-white shadow-[0_1px_2px_rgba(90,71,14,0.35),0_10px_24px_-8px_rgba(156,122,22,0.6)] ' +
    'hover:bg-gold-hover hover:shadow-[0_2px_4px_rgba(90,71,14,0.4),0_16px_32px_-8px_rgba(156,122,22,0.7)]',
  secondary:
    'bg-surface text-ink border border-stone-200 shadow-soft hover:border-stone-300 hover:shadow-card',
  ghost:
    'bg-transparent text-stone-600 hover:bg-stone-100 hover:text-ink',
  danger:
    'bg-danger text-white shadow-[0_1px_2px_rgba(150,40,25,0.35),0_10px_24px_-8px_rgba(195,52,33,0.55)] hover:brightness-[1.05]',
  dark:
    'bg-ink text-white shadow-[0_1px_2px_rgba(0,0,0,0.3),0_12px_28px_-10px_rgba(0,0,0,0.5)] hover:bg-stone-800',
}

const SIZES = {
  sm:  'h-9 px-4 text-[13px] gap-1.5',
  md:  'h-11 px-5 text-sm gap-2',
  lg:  'h-[52px] px-7 text-[15px] gap-2.5',
  icon:'h-11 w-11 p-0 justify-center',
  iconSm: 'h-9 w-9 p-0 justify-center',
}

const Button = forwardRef(function Button(
  { as: Tag = 'button', variant = 'primary', size = 'md', className, children, trailingIcon: Trailing, ...props },
  ref,
) {
  return (
    <Tag
      ref={ref}
      className={cn(
        'group relative inline-flex select-none items-center justify-center rounded-pill font-semibold tracking-tight',
        'transition-all duration-300 ease-expo active:scale-[0.975]',
        'focus-gold disabled:pointer-events-none disabled:opacity-45',
        VARIANTS[variant],
        SIZES[size],
        Trailing && 'pr-2',
        className,
      )}
      {...props}
    >
      {children}
      {Trailing && (
        <span
          className={cn(
            'ml-1 flex h-8 w-8 items-center justify-center rounded-full',
            'transition-transform duration-300 ease-expo',
            'group-hover:translate-x-0.5 group-hover:-translate-y-px group-hover:scale-105',
            variant === 'primary' || variant === 'danger' || variant === 'dark'
              ? 'bg-white/15'
              : 'bg-stone-100 text-ink',
          )}
        >
          <Trailing size={16} strokeWidth={2} />
        </span>
      )}
    </Tag>
  )
})

export default Button
