/**
 * NIRMAN AI — Verification Results Panel
 * Shows pass/fail status for all 6 verification checks with scores and suggestions.
 */
const STATUS_STYLE = {
  pass:    'bg-emerald-900/60 text-emerald-300 border border-emerald-700',
  fail:    'bg-red-900/60    text-red-300    border border-red-700',
  warning: 'bg-yellow-900/60 text-yellow-300 border border-yellow-700',
  skip:    'bg-gray-800      text-gray-400   border border-gray-700',
}

const STATUS_ICON = { pass: '✓', fail: '✗', warning: '⚠', skip: '–' }

function CheckRow({ label, check }) {
  if (!check) return null
  const style = STATUS_STYLE[check.status] || STATUS_STYLE.skip
  const icon  = STATUS_ICON[check.status]  || '?'
  return (
    <div className={`rounded-lg p-3 mb-2 ${style}`}>
      <div className="flex items-center justify-between">
        <span className="font-medium text-sm">{icon} {label}</span>
        {check.score != null && (
          <span className="text-xs opacity-80">score: {(check.score * 100).toFixed(0)}%</span>
        )}
      </div>
      {check.detail && (
        <p className="text-xs mt-1 opacity-80">{check.detail}</p>
      )}
      {check.suggestions?.length > 0 && (
        <ul className="mt-1 pl-3 list-disc text-xs opacity-70 space-y-0.5">
          {check.suggestions.slice(0, 3).map((s, i) => <li key={i}>{s}</li>)}
        </ul>
      )}
    </div>
  )
}

export default function VerificationPanel({ report }) {
  if (!report) return (
    <div className="text-gray-500 text-sm p-4">No verification results yet.</div>
  )

  const overallStyle = report.overall === 'pass'
    ? 'text-emerald-400'
    : 'text-red-400'

  return (
    <div className="p-4 space-y-1">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-sm text-gray-300">Verification Report</h3>
        <div className="flex items-center gap-2">
          <span className={`font-bold text-sm uppercase ${overallStyle}`}>
            {report.overall}
          </span>
          <span className="text-xs text-gray-400">
            {((report.overall_score || 0) * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      <CheckRow label="Execution"             check={report.execution} />
      <CheckRow label="Traversability (BFS)"  check={report.traversability} />
      <CheckRow label="Doorway Clearance"     check={report.doorway_clearance} />
      <CheckRow label="Staircase Access"      check={report.staircase_accessibility} />
      <CheckRow label="Visual Fidelity"       check={report.visual_fidelity} />
      <CheckRow label="Mesh Integrity"        check={report.mesh_integrity} />

      {report.failure_categories?.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-700">
          <p className="text-xs text-gray-400 mb-1">Failure categories:</p>
          <div className="flex flex-wrap gap-1">
            {report.failure_categories.map(cat => (
              <span key={cat} className="px-2 py-0.5 bg-red-900/40 text-red-300 text-xs rounded-full border border-red-800">
                {cat}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
