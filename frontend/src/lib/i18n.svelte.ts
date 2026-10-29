// Tiny translation helper. Each bundle registers its own dictionaries, so the guest bundle never
// carries the internal app's words.
export type Value = string | ((v: Record<string, any>) => string)
export type Dict = Record<string, Value>
export type Lang = 'en' | 'de'
export const LANGS: Lang[] = ['en', 'de']

let current = $state<Lang>('en')
const dicts: Record<Lang, Dict[]> = { en: [], de: [] }

export function register(en: Dict, de: Dict) {
  dicts.en.push(en)
  dicts.de.push(de)
}

export function pickLanguage(...candidates: (string | null | undefined)[]): Lang {
  for (const c of candidates) {
    const two = (c ?? '').toLowerCase().slice(0, 2)
    if (LANGS.includes(two as Lang)) return two as Lang
  }
  return 'en'
}

export function setLanguage(l: string) {
  current = pickLanguage(l)
  document.documentElement.lang = current
}

export function lang(): Lang {
  return current
}

export function t(key: string, v: Record<string, any> = {}): string {
  for (const l of [current, 'en'] as Lang[]) {
    for (const d of dicts[l]) {
      const val = d[key]
      if (val === undefined) continue
      return typeof val === 'function' ? val(v) : val.replace(/\{(\w+)\}/g, (_, k) => String(v[k] ?? ''))
    }
  }
  return key
}

/** "a, b and c" */
export function list(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} ${t('common.and')} ${items[items.length - 1]}`
}

register({ 'common.and': 'and' }, { 'common.and': 'und' })
