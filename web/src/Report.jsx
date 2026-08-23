import { bytes, int, ms, pairImages, pct } from './format.js';

/* The nerdy panel: what the file was, what it became, and the exact path taken to get
   there. Every number here comes straight from the PDF structure -- nothing estimated. */

const Row = ({ label, before, after, mono = true }) => (
  <div className="row">
    <span className="k">{label}</span>
    <span className={`v before ${mono ? 'num' : ''}`}>{before}</span>
    <span className="sep">→</span>
    <span className={`v after ${mono ? 'num' : ''}`}>{after}</span>
  </div>
);

function BudgetBar({ used, target, size }) {
  const over = size > target;
  const fill = Math.min(100, (size / target) * 100);
  return (
    <div className="budget">
      <div className="budget-track">
        <div className={`budget-fill ${over ? 'over' : ''}`} style={{ width: `${fill}%` }} />
      </div>
      <div className="budget-legend">
        <span>{bytes(size)} used</span>
        <span className="dim">
          budget {bytes(target)} · {used}% consumed
        </span>
      </div>
    </div>
  );
}

/* Fidelity: what survived, and how we know. Text and image payloads are compared by
   SHA-1 of their real bytes, so "identical" is a checkable claim rather than a vibe. */
const STATE_LABEL = {
  identical: 'identical',
  reencoded: 're-encoded',
  changed: 'changed',
  lost: 'lost',
  stripped: 'stripped',
  none: 'n/a',
};

function Fidelity({ f, engine }) {
  const rows = [];

  if (f.text.present) {
    rows.push({
      label: 'text layer',
      detail: f.text.identical
        ? `${int(f.text.before)} chars · sha1 ${f.text.sha_before} unchanged`
        : `${int(f.text.before)} → ${int(f.text.after)} chars`,
      state: f.text.identical ? 'identical' : f.text.after === 0 ? 'lost' : 'changed',
    });
  } else {
    rows.push({ label: 'text layer', detail: 'none in source — pure scan', state: 'none' });
  }

  if (f.vectors.present) {
    rows.push({
      label: 'vector art',
      detail: `${int(f.vectors.before)} → ${int(f.vectors.after)} draw ops`,
      state: f.vectors.identical ? 'identical' : f.vectors.after === 0 ? 'lost' : 'changed',
    });
  }

  rows.push({
    label: 'page geometry',
    detail: `${f.geometry.pages_before} pages, ${
      f.geometry.identical ? 'every page size unchanged' : 'page sizes changed'
    }`,
    state: f.geometry.identical ? 'identical' : 'changed',
  });

  if (f.images.present) {
    rows.push({
      label: 'image data',
      detail: f.images.identical
        ? `${f.images.count_before} images · sha1 ${f.images.sha_before} unchanged`
        : `${f.images.count_before} images · sha1 ${f.images.sha_before} → ${f.images.sha_after}`,
      state: f.images.identical ? 'identical' : 'reencoded',
    });
  }

  if (f.metadata_stripped) {
    rows.push({ label: 'metadata', detail: 'producer and XMP removed', state: 'stripped' });
  }

  const verdict = f.lossless
    ? 'Nothing was re-encoded. Every image stream, text run and vector path is byte-for-byte identical — the savings came from structure alone.'
    : engine === 'raster'
      ? 'Every page was flattened to a single image. Text and vector art are gone; this file is now pictures of pages.'
      : f.text.identical && f.vectors.identical && f.geometry.identical
        ? 'Only the image streams were re-encoded. Text, vector art and page geometry came through byte-for-byte identical.'
        : 'Image streams were re-encoded; see the rows above for what else changed.';

  return (
    <Section title="fidelity" note="verified by sha-1 of the actual bytes">
      <div className="rows fid">
        {rows.map(r => (
          <div className="fidrow" key={r.label}>
            <span className="k">{r.label}</span>
            <span className="detail">{r.detail}</span>
            <span className={`state ${r.state}`}>{STATE_LABEL[r.state] || r.state}</span>
          </div>
        ))}
      </div>
      <p className="hintline">{verdict}</p>
    </Section>
  );
}

function Section({ title, note, children }) {
  return (
    <section className="panel">
      <h2>
        {title}
        {note && <span className="note">{note}</span>}
      </h2>
      {children}
    </section>
  );
}

export default function Report({ r }) {
  const b = r.before.doc;
  const a = r.after.doc;
  const pairs = pairImages(r.before.images, r.after.images);
  const peak = Math.max(...r.trace.map(t => t.bytes), r.target);

  return (
    <div className="report">
      <Section title="result">
        <div className="headline">
          <div className="big">
            <span className="was">{bytes(r.original_size)}</span>
            <span className="arrow">→</span>
            <span className="now">{bytes(r.result_size)}</span>
          </div>
          <span className="badge">{r.saved_pct}% smaller</span>
          <span className="badge ratio">{r.ratio}:1</span>
        </div>
        <BudgetBar used={r.budget_used_pct} target={r.target} size={r.result_size} />
        <div className="kv">
          <div>
            <dt>compression</dt>
            <dd className="mintv">
              {r.saved_pct}% · {r.ratio}:1
            </dd>
          </div>
          <div>
            <dt>bytes saved</dt>
            <dd>{bytes(r.saved_bytes)}</dd>
          </div>
          <div>
            <dt>engine</dt>
            <dd>{r.engine}</dd>
          </div>
          <div>
            <dt>setting</dt>
            <dd>{r.setting}</dd>
          </div>
          <div>
            <dt>dpi req → actual</dt>
            <dd>
              {r.dpi_requested ?? '—'} → {a.max_dpi ?? '—'}
            </dd>
          </div>
          <div>
            <dt>jpeg quality</dt>
            <dd>{r.quality ?? '—'}</dd>
          </div>
          <div>
            <dt>grayscale</dt>
            <dd>{r.grayscale ? 'yes' : 'no'}</dd>
          </div>
          <div>
            <dt>probes</dt>
            <dd>{r.probes}</dd>
          </div>
          <div>
            <dt>elapsed</dt>
            <dd>{ms(r.elapsed_ms)}</dd>
          </div>
          <div>
            <dt>headroom</dt>
            <dd>{bytes(r.headroom)}</dd>
          </div>
        </div>
        {!r.met_target && (
          <p className="warn">
            Target unreachable — this is the smallest this file can get. Try the raster
            engine or a larger target.
          </p>
        )}
        {r.engine === 'raster' && (
          <p className="warn">
            Pages were flattened to images: text is no longer selectable or searchable.
          </p>
        )}
      </Section>

      {r.fidelity && <Fidelity f={r.fidelity} engine={r.engine} />}

      <Section title="document" note="before → after">
        <div className="rows">
          <Row label="file size" before={bytes(r.before.bytes)} after={bytes(r.after.bytes)} />
          <Row label="pages" before={int(b.page_count)} after={int(a.page_count)} />
          <Row label="pdf version" before={b.pdf_version || '—'} after={a.pdf_version || '—'} />
          <Row
            label="image payload"
            before={`${bytes(b.image_bytes)} (${b.image_share_pct}%)`}
            after={`${bytes(a.image_bytes)} (${a.image_share_pct}%)`}
          />
          <Row label="images" before={int(r.before.images.length)} after={int(r.after.images.length)} />
          <Row label="max image dpi" before={b.max_dpi ?? '—'} after={a.max_dpi ?? '—'} />
          <Row label="min image dpi" before={b.min_dpi ?? '—'} after={a.min_dpi ?? '—'} />
          <Row label="text chars" before={int(b.text_chars)} after={int(a.text_chars)} />
          <Row label="embedded fonts" before={int(b.embedded_fonts)} after={int(a.embedded_fonts)} />
          <Row label="xref objects" before={int(b.xref_objects)} after={int(a.xref_objects)} />
          <Row label="producer" before={b.producer || '—'} after={a.producer || '—'} mono={false} />
        </div>
        {b.text_chars === 0 && (
          <p className="hintline">
            No text layer in the source — this is a pure scan, so nothing was selectable to
            begin with.
          </p>
        )}
      </Section>

      {pairs.length > 0 && (
        <Section title="images" note={`${pairs.length} tracked`}>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th>pg</th>
                  <th>pixels</th>
                  <th>dpi</th>
                  <th>fmt</th>
                  <th>colorspace</th>
                  <th className="r">bytes</th>
                  <th />
                  <th>pixels</th>
                  <th>dpi</th>
                  <th>fmt</th>
                  <th className="r">bytes</th>
                  <th className="r">Δ</th>
                </tr>
              </thead>
              <tbody>
                {pairs.map(({ before: x, after: y }, i) => {
                  const delta =
                    x.bytes && y?.bytes ? `${Math.round(100 * (1 - y.bytes / x.bytes))}%` : '—';
                  return (
                    <tr key={i}>
                      <td>{x.page}</td>
                      <td className="num">
                        {x.width}×{x.height}
                      </td>
                      <td className="num">{x.dpi_x ?? '—'}</td>
                      <td>{x.format || '—'}</td>
                      <td className="cs" title={x.colorspace}>
                        {x.colorspace || '—'}
                      </td>
                      <td className="num r">{bytes(x.bytes)}</td>
                      <td className="sep">→</td>
                      <td className="num mint">{y ? `${y.width}×${y.height}` : '—'}</td>
                      <td className="num mint">{y?.dpi_x ?? '—'}</td>
                      <td className="mint">{y?.format || '—'}</td>
                      <td className="num r mint">{bytes(y?.bytes)}</td>
                      <td className="num r">{delta}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <Section title="pages">
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>pg</th>
                <th className="r">size (pt)</th>
                <th className="r">size (mm)</th>
                <th className="r">rot</th>
                <th className="r">text</th>
                <th className="r">imgs</th>
                <th className="r">vector ops</th>
                <th className="r">img bytes</th>
                <th className="r">after</th>
              </tr>
            </thead>
            <tbody>
              {r.before.pages.map((p, i) => {
                const q = r.after.pages[i];
                return (
                  <tr key={i}>
                    <td>{p.page}</td>
                    <td className="num r">
                      {p.width_pt}×{p.height_pt}
                    </td>
                    <td className="num r">
                      {p.width_mm}×{p.height_mm}
                    </td>
                    <td className="num r">{p.rotation}°</td>
                    <td className="num r">{int(p.text_chars)}</td>
                    <td className="num r">{p.images}</td>
                    <td className="num r">{int(p.vector_ops)}</td>
                    <td className="num r">{bytes(p.image_bytes)}</td>
                    <td className="num r mint">{bytes(q?.image_bytes)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="search path" note={`${r.probes} probes · ${ms(r.elapsed_ms)}`}>
        <p className="hintline">
          Phase <code>dpi</code> bisects resolution at quality {35}; phase <code>qual</code>{' '}
          then raises quality at the winning resolution until the budget is full. Identical
          sizes across several dpi rungs are JPEG's integer downsampling steps.
        </p>
        <div className="trace">
          {r.trace.map((t, i) => (
            <div key={i} className={`probe ${t.fits ? 'fits' : 'over'}`}>
              <span className="phase">{t.phase}</span>
              <span className="cfg">
                {t.dpi ? `${t.dpi}dpi q${t.quality}${t.gray ? ' gray' : ''}` : 'structural only'}
              </span>
              <span className="bar">
                <span className="bar-fill" style={{ width: `${(t.bytes / peak) * 100}%` }} />
                <span className="bar-target" style={{ left: `${(r.target / peak) * 100}%` }} />
              </span>
              <span className="num sz">{bytes(t.bytes)}</span>
              <span className="verdict">{t.fits ? 'fits' : 'over'}</span>
              <span className="num tms dim">{t.ms}ms</span>
            </div>
          ))}
        </div>
      </Section>

      <a className="download" href={r.download} download={r.filename}>
        download {r.filename} · {bytes(r.result_size)}
      </a>
    </div>
  );
}
