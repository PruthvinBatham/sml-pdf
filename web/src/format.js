// Shared formatters. Kept apart from the components so the report and the header agree
// on exactly how a byte count or a DPI reads.

export const bytes = n => {
  if (n === null || n === undefined) return '—';
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)} MB`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)} KB`;
  return `${n} B`;
};

export const int = n => (n === null || n === undefined ? '—' : n.toLocaleString('en-US'));

export const pct = n => (n === null || n === undefined ? '—' : `${n}%`);

export const ms = n => (n >= 1000 ? `${(n / 1000).toFixed(2)} s` : `${n} ms`);

export const dpi = n => (n ? `${n}` : '—');

// Pair before/after images so a row shows the same physical picture on both sides.
// Images are matched within a page in document order; the raster engine collapses a page
// to a single image, so counts can legitimately differ.
export const pairImages = (before = [], after = []) => {
  const byPage = new Map();
  after.forEach(im => {
    if (!byPage.has(im.page)) byPage.set(im.page, []);
    byPage.get(im.page).push(im);
  });
  const used = new Map();
  return before.map(b => {
    const list = byPage.get(b.page) || [];
    const i = used.get(b.page) || 0;
    used.set(b.page, i + 1);
    return { before: b, after: list[i] || null };
  });
};
