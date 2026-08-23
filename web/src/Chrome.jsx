/* Masthead, colour legend and pipeline strip.

   These exist partly to carry information and partly so the page isn't a single dark box
   with one blue folder in it. The legend is the honest version of a palette showcase: each
   swatch is a colour the report actually uses for that meaning, so learning it here pays
   off when you read the numbers below. */

const LEGEND = [
  { c: 'var(--before)', label: 'before' },
  { c: 'var(--after)', label: 'after' },
  { c: 'var(--accent)', label: 'target' },
  { c: 'var(--warning)', label: 'over budget' },
];

const PHASES = [
  { n: '01', name: 'Clean', desc: 'Remove redundant document data', tone: 'slate' },
  { n: '02', name: 'Balance', desc: 'Find the ideal image resolution', tone: 'teal' },
  { n: '03', name: 'Refine', desc: 'Maximise quality within your target', tone: 'mint' },
];

export function Masthead() {
  return (
    <header className="masthead">
      <div className="brand">
        <span className="mark" aria-hidden="true">S</span>
        <h1>Small PDF</h1>
        <span className="ver"><i /> Local</span>
      </div>
      <p className="eyebrow">Private document compression</p>
      <h2 className="hero-title">Precisely smaller.<br />Beautifully simple.</h2>
      <p className="sub">
        Set the size you need. We find the sharpest result that fits—entirely on your machine.
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
