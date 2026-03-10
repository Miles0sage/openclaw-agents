import React, { useState } from 'react'
import { useStore, BRICK_COLORS } from '../store'

const API_BASE = window.location.origin

const s = {
  panel: {
    width: 270,
    background: 'rgba(15, 15, 35, 0.95)',
    backdropFilter: 'blur(12px)',
    color: '#e0e0e0',
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    overflowY: 'auto',
    borderLeft: '1px solid rgba(255,255,255,0.08)',
  },
  label: { fontSize: 11, textTransform: 'uppercase', letterSpacing: 1.5, color: '#888', fontWeight: 600 },
  textarea: {
    width: '100%', minHeight: 80, padding: '10px', borderRadius: 8,
    border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.05)',
    color: '#fff', fontSize: 13, resize: 'vertical', outline: 'none',
    fontFamily: 'inherit',
  },
  btn: (color, disabled) => ({
    padding: '10px 12px', borderRadius: 8, border: 'none',
    cursor: disabled ? 'not-allowed' : 'pointer',
    background: disabled ? '#333' : (color || '#4361ee'),
    color: disabled ? '#666' : '#fff', fontSize: 13, fontWeight: 600,
    transition: 'all 0.15s', textAlign: 'center', width: '100%',
    opacity: disabled ? 0.6 : 1,
  }),
  result: {
    padding: 12, borderRadius: 8, background: 'rgba(67, 97, 238, 0.1)',
    border: '1px solid rgba(67, 97, 238, 0.2)', fontSize: 13,
    lineHeight: 1.5, maxHeight: 250, overflowY: 'auto', whiteSpace: 'pre-wrap',
  },
  divider: { height: 1, background: 'rgba(255,255,255,0.06)', margin: '4px 0' },
  statusDot: (ok) => ({
    display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
    background: ok ? '#22c55e' : '#ef4444', marginRight: 6,
  }),
}

// Convert frontend brick format to backend format
function bricksToAPI(bricks) {
  return bricks.map(b => ({
    x: b.position[0],
    y: b.position[1],
    z: b.position[2],
    color: b.color,
    size: `${b.width}x${b.depth}`,
  }))
}

// Convert backend suggestion to frontend brick format
function suggestionToFrontend(sug) {
  const sizeMap = { 'small': [1,1], 'standard': [2,2], 'large': [2,4] }
  let w = 2, d = 2
  if (sug.size && sug.size.includes('x')) {
    const parts = sug.size.split('x').map(Number)
    if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
      w = parts[0]; d = parts[1]
    }
  } else if (sizeMap[sug.size]) {
    [w, d] = sizeMap[sug.size]
  }
  // Map color name to hex if needed
  const hex = sug.color.startsWith('#') ? sug.color
    : (BRICK_COLORS.find(c => c.name.toLowerCase() === sug.color.toLowerCase())?.hex || sug.color)
  return {
    position: [sug.x || 0, sug.y || 0, sug.z || 0],
    color: hex,
    width: w,
    depth: d,
  }
}

async function callAI(endpoint, bricks, prompt = '') {
  const body = {
    bricks: bricksToAPI(bricks),
    context: prompt || undefined,
    count: 5,
  }
  const res = await fetch(`${API_BASE}/api/ai/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `API error: ${res.status}`)
  }
  return res.json()
}

export default function AIPanel() {
  const bricks = useStore((st) => st.bricks)
  const aiLoading = useStore((st) => st.aiLoading)
  const aiResult = useStore((st) => st.aiResult)
  const { setAiLoading, setAiResult, loadBricksFromAI } = useStore()
  const [prompt, setPrompt] = useState('')
  const [ollamaOk, setOllamaOk] = useState(null)

  // Check Ollama on mount
  React.useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then(r => r.json())
      .then(d => setOllamaOk(d.status === 'ok'))
      .catch(() => setOllamaOk(false))
  }, [])

  const handleSuggest = async () => {
    setAiLoading(true)
    setAiResult(null)
    try {
      const data = await callAI('suggest', bricks, prompt)
      const text = data.analysis || ''
      const reasons = (data.suggestions || []).map(s => s.reason).filter(Boolean).join('\n')
      setAiResult(text + (reasons ? '\n\n' + reasons : ''))
      if (data.suggestions?.length) {
        const mapped = data.suggestions.map(suggestionToFrontend)
        loadBricksFromAI(mapped)
      }
    } catch (err) {
      setAiResult(`Error: ${err.message}`)
    } finally {
      setAiLoading(false)
    }
  }

  const handleComplete = async () => {
    if (!prompt.trim()) {
      setAiResult('Please describe what to complete (e.g. "finish this wall", "add a roof")')
      return
    }
    setAiLoading(true)
    setAiResult(null)
    try {
      const data = await callAI('complete', bricks, prompt)
      setAiResult(data.completion_description || 'Build completed')
      if (data.added_bricks?.length) {
        const mapped = data.added_bricks.map(suggestionToFrontend)
        loadBricksFromAI(mapped)
      }
    } catch (err) {
      setAiResult(`Error: ${err.message}`)
    } finally {
      setAiLoading(false)
    }
  }

  const handleDescribe = async () => {
    setAiLoading(true)
    setAiResult(null)
    try {
      const data = await callAI('describe', bricks, prompt)
      const parts = [data.description]
      if (data.structure_type && data.structure_type !== 'unknown') parts.push(`Type: ${data.structure_type}`)
      if (data.complexity) parts.push(`Complexity: ${data.complexity}`)
      setAiResult(parts.join('\n'))
    } catch (err) {
      setAiResult(`Error: ${err.message}`)
    } finally {
      setAiLoading(false)
    }
  }

  return (
    <div style={s.panel}>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={s.label}>AI Assistant</div>
        <div style={{ fontSize: 11, color: '#666' }}>
          <span style={s.statusDot(ollamaOk)} />
          {ollamaOk === null ? 'checking...' : ollamaOk ? 'Ollama connected' : 'Ollama offline'}
        </div>
      </div>

      <textarea
        style={s.textarea}
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="Describe what you want to build...&#10;e.g. &quot;build a red tower&quot; or &quot;add a roof&quot;"
      />

      <button
        style={s.btn('#4361ee', aiLoading)}
        onClick={handleSuggest}
        disabled={aiLoading}
      >
        {aiLoading ? 'Thinking...' : 'AI Suggest'}
      </button>
      <button
        style={s.btn('#7c3aed', aiLoading)}
        onClick={handleComplete}
        disabled={aiLoading}
      >
        {aiLoading ? 'Thinking...' : 'AI Complete'}
      </button>
      <button
        style={s.btn('#0d9488', aiLoading)}
        onClick={handleDescribe}
        disabled={aiLoading}
      >
        {aiLoading ? 'Thinking...' : 'AI Describe'}
      </button>

      <div style={s.divider} />

      {aiResult && (
        <div>
          <div style={s.label}>AI Response</div>
          <div style={s.result}>{aiResult}</div>
        </div>
      )}

      <div style={{ fontSize: 11, color: '#555', lineHeight: 1.6, marginTop: 'auto' }}>
        <strong style={{ color: '#4361ee' }}>Suggest</strong> — AI adds bricks based on your prompt<br />
        <strong style={{ color: '#7c3aed' }}>Complete</strong> — AI finishes your build (needs description)<br />
        <strong style={{ color: '#0d9488' }}>Describe</strong> — AI describes what you've built<br />
        <div style={{ marginTop: 6, color: '#444' }}>Powered by Ollama (qwen2.5-coder:7b)</div>
      </div>
    </div>
  )
}
