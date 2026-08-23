/* Masthead, colour legend and pipeline strip.

   These exist partly to carry information and partly so the page isn't a single dark box
   with one blue folder in it. The legend is the honest version of a palette showcase: each
   swatch is a colour the report actually uses for that meaning, so learning it here pays
   off when you read the numbers below. */

const LEGEND = [
  { c: 'var(--sand)', label: 'before' },
  { c: 'var(--mint)', label: 'after' },
  { c: 'var(--fog)', label: 'target' },
  { c: 'var(--peach)', label: 'over budget' },
];

const PHASES = [
  { n: '00', name: 'lossless', desc: 'strip metadata, subset fonts, rebuild xref', tone: 'slate' },
  { n: '01', name: 'resolution', desc: 'bisect the dpi ladder at probe quality', tone: 'teal' },
  { n: '02', name: 'quality', desc: 'raise jpeg quality until the budget is full', tone: 'mint' },
];

export function Masthead() {
  return (
    <header className="masthead">
      <div className="brand">
        <span className="mark">sml</span>
        <span className="slash">/</span>
        <h1>pdf compress</h1>
        <span className="ver">local</span>
      </div>
      <p className="sub">
        Name a file size. Get that file size — with the sharpest image settings that fit
        inside it, and a full structural read-out of what changed.
      </p>
      <div className="legend">
        {LEGEND.map(l => (
          <span className="chip" key={l.label}>
            <i style={{ background: l.c }} />
            {l.label}
          </span>
        ))}
      </div>
    </header>
  );
}

export function Pipeline() {
  return (
    <div className="pipeline">
      {PHASES.map(p => (
        <div className={`step ${p.tone}`} key={p.n}>
          <span className="n">{p.n}</span>
          <span className="name">{p.name}</span>
          <span className="desc">{p.desc}</span>
        </div>
      ))}
    </div>
  );
}
