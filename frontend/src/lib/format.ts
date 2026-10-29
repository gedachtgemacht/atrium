import { lang, t } from './i18n.svelte'

const locale = () => (lang() === 'de' ? 'de-DE' : 'en-GB')

export const time = (iso: string) => new Intl.DateTimeFormat(locale(), { hour: '2-digit', minute: '2-digit' }).format(new Date(iso))
export const eur = (n: number) =>
  new Intl.NumberFormat(lang() === 'de' ? 'de-DE' : 'en-IE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(Math.round(n))

const dayFmt = () => new Intl.DateTimeFormat(locale(), { weekday: 'long', day: 'numeric', month: 'long' })

export function dayLabel(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const y = new Date()
  y.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return t('date.today')
  if (d.toDateString() === y.toDateString()) return t('date.yesterday')
  return dayFmt().format(d)
}

export function when(iso: string): string {
  const d = new Date(iso)
  return d.toDateString() === new Date().toDateString() ? t('date.today_at', { time: time(iso) }) : `${dayFmt().format(d)}, ${time(iso)}`
}

export function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', lang() === 'de' ? ',' : '.')} MB`
}

export function firstName(name: string): string {
  return name.split(' ')[0] ?? name
}

/** Split text into plain parts and @mentions, for safe rendering without innerHTML. */
export function parts(text: string): { text: string; mention: boolean }[] {
  const out: { text: string; mention: boolean }[] = []
  const re = /(?<![\w@])@[A-Za-zÀ-ÿ][\w.-]{1,59}/g
  let last = 0
  for (const m of text.matchAll(re)) {
    if (m.index! > last) out.push({ text: text.slice(last, m.index), mention: false })
    out.push({ text: m[0], mention: true })
    last = m.index! + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last), mention: false })
  return out
}
