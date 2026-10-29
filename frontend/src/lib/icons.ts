// Icons from the mockup, as static SVG strings (no user content ever goes in here).
const s = (w: number, body: string, sw = 2, extra = '') =>
  `<svg width="${w}" height="${w}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw}"${extra} aria-hidden="true">${body}</svg>`

export const icons = {
  lock: (w = 13) => s(w, '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
  arrow: (w = 13) => s(w, '<path d="M5 12h12M13 7l5 5-5 5"/>', 2.2, ' stroke-linecap="round" stroke-linejoin="round"'),
  check: (w = 16) => s(w, '<path d="m5 12 5 5 9-10"/>', 2.4, ' stroke-linecap="round" stroke-linejoin="round"'),
  pen: (w = 12) => s(w, '<path d="M4 20h4L19 9l-4-4L4 16z"/>', 2.2, ' stroke-linejoin="round"'),
  info: (w = 15) => s(w, '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5v.01"/>', 2, ' stroke-linecap="round"'),
  doc: (w = 22) => s(w, '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>', 1.8, ' stroke-linejoin="round"'),
  mark: (w = 13) => s(w, '<path d="M6 3h12v18l-6-4-6 4z"/>', 2.2, ' stroke-linejoin="round"'),
  eye: (w = 15) => s(w, '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  person: (w = 13) => s(w, '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>', 2.2),
  search: (w = 16) => s(w, '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', 2, ' stroke-linecap="round"'),
  menu: (w = 18) => s(w, '<path d="M4 7h16M4 12h16M4 17h16"/>', 2, ' stroke-linecap="round"'),
  x: (w = 14) => s(w, '<path d="M6 6l12 12M18 6 6 18"/>', 2.2, ' stroke-linecap="round"'),
  server: (w = 13) => s(w, '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/>'),
  clip: (w = 18) => s(w, '<path d="m21 11-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 7"/>', 2, ' stroke-linecap="round" stroke-linejoin="round"'),
  trash: (w = 14) => s(w, '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>', 2, ' stroke-linejoin="round"'),
  link: (w = 14) => s(w, '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>', 2, ' stroke-linecap="round"'),
  gear: (w = 14) => s(w, '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>', 2, ' stroke-linecap="round"'),
}
