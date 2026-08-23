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
      >
        <span className="bracket tl" />
        <span className="bracket tr" />
        <span className="bracket bl" />
        <span className="bracket br" />
        <div className={`stage ${dragging || file ? 'open' : 'closed'}`}>
          <Folder size={1.15} color="#26408B" open={dragging || !!file} />
        </div>
        <p className="hint">
          {file ? (
            <>
              <strong>{file.name}</strong>
              <span className="dim"> · {bytes(file.size)}</span>
            </>
          ) : (
            'drop a pdf here, or click to browse'
          )}
        </p>
        <p className="spec">pdf only · up to 300 mb · processed on this machine</p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          hidden
          onChange={e => pick(e.target.files?.[0])}
        />
      </div>

      <div className="controls">
        <label htmlFor="amount">target</label>
        <input
          id="amount"
          type="number"
          min="0.05"
          step="0.05"
          value={amount}
          onChange={e => setAmount(e.target.value)}
        />
        <select value={unit} onChange={e => setUnit(e.target.value)} aria-label="Unit">
          <option>MB</option>
          <option>KB</option>
        </select>
        <label htmlFor="engine">engine</label>
        <select id="engine" value={mode} onChange={e => setMode(e.target.value)}>
          <option value="auto">auto</option>
          <option value="images">images only</option>
          <option value="raster">raster only</option>
        </select>
        <button onClick={compress} disabled={!file || busy}>
          {busy ? 'compressing…' : 'compress'}
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
