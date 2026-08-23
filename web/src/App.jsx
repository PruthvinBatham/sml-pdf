import { useRef, useState } from 'react';
import Folder from './Folder.jsx';
import Report from './Report.jsx';
import { Masthead, Pipeline } from './Chrome.jsx';
import { bytes } from './format.js';

const UNITS = { MB: 1e6, KB: 1e3 };

export default function App() {
  const [file, setFile] = useState(null);
  const [amount, setAmount] = useState('1');
  const [unit, setUnit] = useState('MB');
  const [mode, setMode] = useState('auto');
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  const pick = next => {
    if (!next) return;
    if (next.type !== 'application/pdf' && !next.name.toLowerCase().endsWith('.pdf')) {
      setError('Not a PDF.');
      return;
    }
    setFile(next);
    setReport(null);
    setError(null);
  };

  const compress = async () => {
    const target = Math.round(parseFloat(amount) * UNITS[unit]);
    if (!file || !Number.isFinite(target) || target <= 0) {
      setError('Enter a target size above zero.');
      return;
    }
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const q = new URLSearchParams({ target: String(target), mode, name: file.name });
      const res = await fetch(`/api/compress?${q}`, { method: 'POST', body: file });
      const payload = await res.json();
      if (!res.ok) throw new Error(payload.error || `server returned ${res.status}`);
      setReport(payload);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="wrap">
      <Masthead />

      <div
        className={`drop ${dragging ? 'over' : ''}`}
        role="button"
        tabIndex={0}
        aria-label={file ? `Selected ${file.name}. Choose a different PDF` : 'Choose a PDF to compress'}
        onDragOver={e => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault();
          setDragging(false);
          pick(e.dataTransfer.files?.[0]);
        }}
        onClick={() => inputRef.current?.click()}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
      >
        <span className="bracket tl" />
        <span className="bracket tr" />
        <span className="bracket bl" />
        <span className="bracket br" />
        <div className={`stage ${dragging || file ? 'open' : 'closed'}`}>
          <Folder size={1.05} color="#49658F" open={dragging || !!file} />
        </div>
        <span className="drop-label">{file ? 'Ready to compress' : 'Choose your document'}</span>
        <p className="hint">
          {file ? (
            <>
              <strong>{file.name}</strong>
              <span className="dim"> · {bytes(file.size)}</span>
            </>
          ) : (
            'Drop a PDF here or browse files'
          )}
        </p>
        <p className="spec">PDF only <i /> Up to 300 MB <i /> Never leaves this device</p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          hidden
          onChange={e => pick(e.target.files?.[0])}
        />
      </div>

      <div className="controls" aria-label="Compression settings">
        <div className="control-group target-control">
          <label htmlFor="amount">Target size</label>
          <div className="joined-control">
            <input id="amount" type="number" min="0.05" step="0.05" value={amount} onChange={e => setAmount(e.target.value)} />
            <select value={unit} onChange={e => setUnit(e.target.value)} aria-label="Unit">
              <option>MB</option><option>KB</option>
            </select>
          </div>
        </div>
        <div className="control-group engine-control">
          <label htmlFor="engine">Compression</label>
          <select id="engine" value={mode} onChange={e => setMode(e.target.value)}>
            <option value="auto">Automatic</option>
            <option value="images">Images only</option>
            <option value="raster">Raster only</option>
          </select>
        </div>
        <button onClick={compress} disabled={!file || busy}>
          {busy ? 'Compressing…' : 'Compress PDF'}
        </button>
      </div>

      {!report && !busy && <Pipeline />}

      {busy && (
        <p className="working">
          bisecting settings<span className="dots" /> — large scans take a few seconds
        </p>
      )}
      {error && <p className="error">{error}</p>}
      {report && <Report r={report} />}

      <footer>
        {report?.versions
          ? `pymupdf ${report.versions.pymupdf} · python ${report.versions.python} · `
          : ''}
        two-phase bisection: resolution, then quality
      </footer>
    </main>
  );
}
