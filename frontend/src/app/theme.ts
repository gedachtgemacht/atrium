// Light, dark or like the system. A per-browser preference, so it lives in localStorage.
export type Theme = 'auto' | 'light' | 'dark'

export function getTheme(): Theme {
  try {
    const v = localStorage.getItem('atrium.theme')
    return v === 'light' || v === 'dark' ? v : 'auto'
  } catch {
    return 'auto'
  }
}

export function applyTheme(theme: Theme = getTheme()) {
  if (theme === 'auto') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', theme)
  try {
    if (theme === 'auto') localStorage.removeItem('atrium.theme')
    else localStorage.setItem('atrium.theme', theme)
  } catch {}
}
