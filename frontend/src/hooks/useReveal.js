import { useEffect, useRef } from 'react'

// IntersectionObserver-driven scroll reveal. Adds `.is-in` to elements
// carrying the `.reveal` class as they enter the viewport (once).
// Attach the returned ref to any container; every `.reveal` descendant
// (and the container itself, if it has the class) is observed.
export function useReveal(deps = []) {
  const ref = useRef(null)

  useEffect(() => {
    const root = ref.current
    if (!root) return

    const targets = []
    if (root.classList?.contains('reveal')) targets.push(root)
    root.querySelectorAll?.('.reveal').forEach((el) => targets.push(el))
    if (targets.length === 0) return

    if (!('IntersectionObserver' in window)) {
      targets.forEach((el) => el.classList.add('is-in'))
      return
    }

    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-in')
            io.unobserve(entry.target)
          }
        })
      },
      { threshold: 0.12, rootMargin: '0px 0px -8% 0px' },
    )

    targets.forEach((el) => io.observe(el))
    return () => io.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return ref
}
