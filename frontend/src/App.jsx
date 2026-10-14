/**
 * NIRMAN AI — Main Application
 * Connects photo upload, graph context view, generation, 3D viewport,
 * verification panel, attempt history, and feedback controls.
 */
import { useState, useCallback } from 'react'
import Viewer3D from './Viewer3D'
import VerificationPanel from './VerificationPanel'
import {
  uploadPhotos, generateBuilding, listAttempts,
  submitFeedback, getFailurePatterns, gltfUrl,
} from './api'

const TABS = ['Generate', 'History', 'Graph', 'Patterns']

// ── Utilities ─────────────────────────────────────────────────────────────────

function cls(...c) { return c.filter(Boolean).join(' ') }

function Badge({ color = 'gray', children }) {
  const colors = {
    green:  'bg-emerald-900/60 text-emerald-300 border-emerald-700',
    red:    'bg-red-900/60    text-red-300    border-red-700',
    yellow: 'bg-yellow-900/60 text-yellow-300 border-yellow-700',
    gray:   'bg-gray-800      text-gray-400   border-gray-700',
    blue:   'bg-blue-900/60   text-blue-300   border-blue-700',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full border text-xs font-medium ${colors[color] || colors.gray}`}>
      {children}
    </span>
  )
}

// ── Photo upload panel ────────────────────────────────────────────────────────

function PhotoUploader({ buildingId, onUploaded }) {
  const [files,   setFiles]   = useState([])
  const [prompts, setPrompts] = useState([])
  const [hints,   setHints]   = useState([])
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const handleFiles = (e) => {
    const selected = Array.from(e.target.files)
    setFiles(selected)
    setPrompts(selected.map(() => ''))
    setHints(selected.map(() => ''))
  }

  const upload = async () => {
    if (!files.length) return
    setLoading(true); setError(null)
    try {
      const res = await uploadPhotos(buildingId, files, prompts, hints)
      onUploaded(res.data)
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="text-xs text-gray-400 mb-1 block">Building photographs</span>
        <input
          type="file" multiple accept="image/*"
          onChange={handleFiles}
          className="block w-full text-sm text-gray-300 file:mr-3 file:py-1.5 file:px-3
                     file:rounded file:border-0 file:bg-indigo-600 file:text-white
                     file:text-xs cursor-pointer"
        />
      </label>

      {files.map((f, i) => (
        <div key={i} className="bg-gray-800 rounded-lg p-2 space-y-1">
          <p className="text-xs text-gray-300 font-medium truncate">{f.name}</p>
          <input
            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-600"
            placeholder="Photo prompt (optional)"
            value={prompts[i] || ''}
            onChange={e => { const p=[...prompts]; p[i]=e.target.value; setPrompts(p) }}
          />
          <input
            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-600"
            placeholder="Hint: exterior / stairs / ground / upper / roof"
            value={hints[i] || ''}
            onChange={e => { const h=[...hints]; h[i]=e.target.value; setHints(h) }}
          />
        </div>
      ))}

      {error && <p className="text-xs text-red-400">{error}</p>}

      <button
        onClick={upload} disabled={!files.length || loading}
        className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40
                   rounded text-sm font-medium transition-colors"
      >
        {loading ? 'Uploading…' : `Upload ${files.length} photo(s)`}
      </button>
    </div>
  )
}

// ── Generation panel ──────────────────────────────────────────────────────────

function GeneratePanel({ buildingId, onResult }) {
  const [prompt,   setPrompt]   = useState('')
  const [bestOfN,  setBestOfN]  = useState(true)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const generate = async () => {
    if (!prompt.trim()) return
    setLoading(true); setError(null)
    try {
      const res = await generateBuilding(buildingId, prompt, bestOfN)
      onResult(res.data)
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-3">
      <textarea
        rows={4}
        className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2
                   text-sm text-gray-200 placeholder-gray-600 resize-none focus:outline-none
                   focus:border-indigo-500"
        placeholder="Describe the building: floors, rooms, layout, style…"
        value={prompt}
        onChange={e => setPrompt(e.target.value)}
      />
      <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer select-none">
        <input type="checkbox" checked={bestOfN} onChange={e => setBestOfN(e.target.checked)}
               className="rounded" />
        Best-of-N selection (generate {3} candidates, pick highest score)
      </label>
      {error && <p className="text-xs text-red-400">{error}</p>}
      <button
        onClick={generate} disabled={!prompt.trim() || loading}
        className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40
                   rounded text-sm font-medium transition-colors"
      >
        {loading ? 'Generating 3D building…' : '⚡ Generate Building'}
      </button>
    </div>
  )
}

// ── Attempt history ───────────────────────────────────────────────────────────

function AttemptHistory({ buildingId, onSelect }) {
  const [attempts, setAttempts] = useState([])
  const [loading,  setLoading]  = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await listAttempts(buildingId)
      setAttempts(res.data.attempts || [])
    } finally { setLoading(false) }
  }

  return (
    <div>
      <button onClick={load} disabled={loading}
              className="mb-3 text-xs text-indigo-400 hover:text-indigo-300">
        {loading ? 'Loading…' : '↻ Refresh attempts'}
      </button>
      <div className="space-y-2">
        {attempts.map(a => (
          <div key={a.id}
               className="bg-gray-800 rounded-lg p-3 cursor-pointer hover:bg-gray-750 border border-gray-700"
               onClick={() => onSelect(a)}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-gray-400 font-mono">{a.id.slice(0,8)}…</span>
              <Badge color={a.verification_overall === 'pass' ? 'green' : 'red'}>
                {a.verification_overall}
              </Badge>
            </div>
            <p className="text-xs text-gray-300 truncate">{a.user_request}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs text-gray-500">
                score: {((a.verification_score || 0) * 100).toFixed(0)}%
              </span>
              <span className="text-xs text-gray-500">·</span>
              <span className="text-xs text-gray-500">{a.strategy}</span>
              {a.accepted && <Badge color="green">accepted</Badge>}
            </div>
          </div>
        ))}
        {!loading && !attempts.length && (
          <p className="text-xs text-gray-600">No attempts yet.</p>
        )}
      </div>
    </div>
  )
}

// ── Feedback panel ────────────────────────────────────────────────────────────

function FeedbackBar({ buildingId, attemptId, onFeedback }) {
  const [text,    setText]    = useState('')
  const [loading, setLoading] = useState(false)
  const [done,    setDone]    = useState(false)

  const submit = async (accepted) => {
    setLoading(true)
    try {
      await submitFeedback(buildingId, attemptId, text || (accepted ? 'accepted' : 'rejected'), accepted)
      onFeedback(accepted)
      setDone(true)
    } finally { setLoading(false) }
  }

  if (done) return <p className="text-xs text-emerald-400 text-center py-2">Feedback recorded ✓</p>

  return (
    <div className="flex flex-col gap-2 p-3 bg-gray-800 rounded-lg border border-gray-700">
      <p className="text-xs text-gray-400 font-medium">Rate this generation:</p>
      <input
        className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs
                   text-gray-200 placeholder-gray-600"
        placeholder="Optional feedback text…"
        value={text}
        onChange={e => setText(e.target.value)}
      />
      <div className="flex gap-2">
        <button onClick={() => submit(true)} disabled={loading}
                className="flex-1 py-1.5 bg-emerald-700 hover:bg-emerald-600 rounded text-xs font-medium">
          ✓ Accept
        </button>
        <button onClick={() => submit(false)} disabled={loading}
                className="flex-1 py-1.5 bg-red-800 hover:bg-red-700 rounded text-xs font-medium">
          ✗ Reject
        </button>
      </div>
    </div>
  )
}

// ── Failure pattern panel ─────────────────────────────────────────────────────

function FailurePatternPanel({ buildingId }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await getFailurePatterns(buildingId)
      setData(res.data)
    } finally { setLoading(false) }
  }

  return (
    <div>
      <button onClick={load} disabled={loading}
              className="mb-3 text-xs text-indigo-400 hover:text-indigo-300">
        {loading ? 'Loading…' : '↻ Load failure patterns'}
      </button>
      {data && (
        <div className="space-y-2">
          {data.corrective_hints?.map((h, i) => (
            <div key={i} className="bg-gray-800 rounded-lg p-2 border border-gray-700">
              <div className="flex items-center justify-between mb-1">
                <Badge color="red">{h.failure_category}</Badge>
                <span className="text-xs text-gray-500">×{h.occurrences}</span>
              </div>
              <p className="text-xs text-gray-400">{h.correction}</p>
            </div>
          ))}
          {!data.corrective_hints?.length && (
            <p className="text-xs text-gray-600">No recurring failures recorded.</p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Root App ──────────────────────────────────────────────────────────────────

export default function App() {
  const [buildingId,    setBuildingId]    = useState('building_001')
  const [uploaded,      setUploaded]      = useState(null)
  const [genResult,     setGenResult]     = useState(null)
  const [activeAttempt, setActiveAttempt] = useState(null)
  const [activeTab,     setActiveTab]     = useState('Generate')
  const [showFeedback,  setShowFeedback]  = useState(false)

  const viewReport = activeAttempt?.verification_report || genResult?.verification_report_detail
  const currentGltfUrl = genResult?.gltf_available
    ? gltfUrl(genResult.attempt_id, buildingId)
    : null

  const handleGenResult = (res) => {
    setGenResult(res)
    setShowFeedback(true)
    setActiveAttempt(null)
  }

  return (
    <div className="h-screen flex flex-col bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="h-12 bg-gray-900 border-b border-gray-800 flex items-center px-4 gap-4 shrink-0">
        <span className="font-bold text-indigo-400 text-base tracking-tight">NIRMAN AI</span>
        <span className="text-gray-600 text-xs hidden sm:block">
          Graph-guided 3D Building Generation
        </span>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-gray-500">Building ID:</span>
          <input
            className="bg-gray-800 border border-gray-700 rounded px-2 py-0.5 text-xs
                       text-gray-300 w-32 focus:outline-none focus:border-indigo-500"
            value={buildingId}
            onChange={e => setBuildingId(e.target.value)}
          />
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Left panel */}
        <aside className="w-80 bg-gray-900 border-r border-gray-800 flex flex-col overflow-y-auto shrink-0">
          {/* Upload section */}
          <div className="p-4 border-b border-gray-800">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
              1. Upload Photos
            </h2>
            <PhotoUploader buildingId={buildingId} onUploaded={setUploaded} />
            {uploaded && (
              <div className="mt-2 text-xs text-emerald-400">
                ✓ {uploaded.photos_uploaded} photos → {uploaded.cells_created} cells
              </div>
            )}
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-800">
            {TABS.map(t => (
              <button key={t}
                      onClick={() => setActiveTab(t)}
                      className={cls(
                        'flex-1 py-2 text-xs font-medium transition-colors',
                        activeTab === t
                          ? 'text-indigo-400 border-b-2 border-indigo-400 bg-gray-850'
                          : 'text-gray-500 hover:text-gray-300'
                      )}>
                {t}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 p-4 overflow-y-auto">
            {activeTab === 'Generate' && (
              <>
                <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  2. Generate Building
                </h2>
                <GeneratePanel buildingId={buildingId} onResult={handleGenResult} />

                {genResult && (
                  <div className="mt-4 space-y-2">
                    <div className="flex items-center gap-2">
                      <Badge color={genResult.success ? 'green' : 'red'}>
                        {genResult.success ? 'Success' : 'Failed'}
                      </Badge>
                      <Badge color={genResult.verification_overall === 'pass' ? 'green' : 'red'}>
                        {genResult.verification_overall}
                      </Badge>
                      <span className="text-xs text-gray-500 ml-auto">
                        {((genResult.verification_score || 0) * 100).toFixed(0)}%
                      </span>
                    </div>
                    {showFeedback && (
                      <FeedbackBar
                        buildingId={buildingId}
                        attemptId={genResult.attempt_id}
                        onFeedback={() => setShowFeedback(false)}
                      />
                    )}
                  </div>
                )}
              </>
            )}

            {activeTab === 'History' && (
              <>
                <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Generation History
                </h2>
                <AttemptHistory
                  buildingId={buildingId}
                  onSelect={(a) => { setActiveAttempt(a); setActiveTab('Generate') }}
                />
              </>
            )}

            {activeTab === 'Graph' && (
              <>
                <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Photo-Cell Graph
                </h2>
                {uploaded ? (
                  <div className="space-y-2">
                    {uploaded.cells?.map(c => (
                      <div key={c.id} className="bg-gray-800 rounded-lg p-2 border border-gray-700">
                        <div className="flex items-center justify-between">
                          <Badge color="blue">{c.type.replace(/_/g, ' ')}</Badge>
                          <span className="text-xs text-gray-500">{c.photos} photo(s)</span>
                        </div>
                        <p className="text-xs text-gray-500 font-mono mt-1 truncate">{c.id}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-gray-600">Upload photos first to view the graph.</p>
                )}
              </>
            )}

            {activeTab === 'Patterns' && (
              <>
                <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  Failure Patterns
                </h2>
                <FailurePatternPanel buildingId={buildingId} />
              </>
            )}
          </div>
        </aside>

        {/* Center — 3D Viewport */}
        <main className="flex-1 relative">
          <Viewer3D gltfUrl={currentGltfUrl} />
          {!currentGltfUrl && (
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <div className="text-6xl mb-4 opacity-20">🏗️</div>
              <p className="text-gray-600 text-sm">Upload photos and generate to see your building</p>
            </div>
          )}
        </main>

        {/* Right panel — Verification */}
        <aside className="w-72 bg-gray-900 border-l border-gray-800 overflow-y-auto shrink-0">
          <div className="p-4 border-b border-gray-800">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
              3. Verification Results
            </h2>
          </div>
          <VerificationPanel
            report={
              activeAttempt?.verification_report
              || (genResult ? {
                  overall:        genResult.verification_overall,
                  overall_score:  genResult.verification_score,
                  attempt_id:     genResult.attempt_id,
                } : null)
            }
          />
        </aside>
      </div>
    </div>
  )
}
