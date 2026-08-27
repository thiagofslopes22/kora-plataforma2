import { useState, useEffect } from 'react'

// Animated processing screen — transform/opacity only.
export default function ProcessingView({
  title = 'Conciliando arquivos…',
  steps = ['Lendo os arquivos', 'Comparando célula a célula', 'Classificando divergências', 'Montando o resultado'],
  note = 'Isso costuma levar alguns segundos.',
}) {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setI((v) => (v + 1) % steps.length), 1400)
    return () => clearInterval(t)
  }, [steps.length])

  return (
    <div className="flex min-h-[52vh] flex-col items-center justify-center py-16 text-center animate-fade-in">
      <div className="relative mb-9 flex h-24 w-24 items-center justify-center">
        <span className="absolute inset-0 rounded-full bg-gold-wash animate-pulse-ring" />
        <span className="absolute inset-0 rounded-full border border-gold/20" />
        <span className="h-16 w-16 animate-spin-slow rounded-full border-[3px] border-gold/20 border-t-gold" />
        <span className="absolute h-2.5 w-2.5 rounded-full bg-gold" />
      </div>

      <h2 className="font-display text-[22px] font-semibold tracking-tight text-ink">{title}</h2>

      <div className="mt-5 h-6 overflow-hidden">
        {steps.map((s, idx) => (
          <p
            key={idx}
            className="text-[14px] font-medium text-stone-500 transition-all duration-500 ease-expo"
            style={{
              transform: `translateY(${(idx - i) * 24}px)`,
              opacity: idx === i ? 1 : 0,
            }}
          >
            {s}…
          </p>
        ))}
      </div>

      <div className="mt-6 flex items-center gap-1.5">
        {steps.map((_, idx) => (
          <span
            key={idx}
            className="h-1.5 rounded-full bg-gold transition-all duration-500 ease-expo"
            style={{ width: idx === i ? 22 : 6, opacity: idx === i ? 1 : 0.25 }}
          />
        ))}
      </div>

      <p className="mt-8 max-w-xs text-[12.5px] leading-relaxed text-stone-400">{note}</p>
    </div>
  )
}
