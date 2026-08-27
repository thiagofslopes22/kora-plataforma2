// Minimal className joiner — filters falsy, flattens.
export function cn(...args) {
  return args
    .flat(Infinity)
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim()
}
