import React, { useState, useRef, useEffect } from 'react'
import { useStore, BRICK_COLORS, BRICK_SIZES } from '../store'

const s = {
  sidebar: {
    width: 240,
    background: 'rgba(15, 15, 35, 0.95)',
    backdropFilter: 'blur(12px)',
    color: '#e0e0e0',
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
    overflowY: 'auto',
    borderRight: '1px solid rgba(255,255,255,0.08)',
  },
  section: { display: 'flex', flexDirection: 'column', gap: 6 },
  label: { fontSize: 11, textTransform: 'uppercase', letterSpacing: 1.5, color: '#888', fontWeight: 600 },
  colorGrid: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 },
  colorSwatch: (hex, selected) => ({
    width: '100%', aspectRatio: '1', borderRadius: 6, background: hex, cursor: 'pointer',
    border: selected ? '3px solid #fff' : '2px solid rgba(255,255,255,0.15)',
    transition: 'all 0.15s',
    boxShadow: selected ? `0 0 10px ${hex}66` : 'none',
  }),
  sizeGrid: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4 },
  sizeBtn: (selected) => ({
    padding: '6px 0', borderRadius: 6, border: 'none', cursor: 'pointer',
    background: selected ? '#4361ee' : 'rgba(255,255,255,0.08)',
    color: selected ? '#fff' : '#aaa', fontSize: 12, fontWeight: 600,
    transition: 'all 0.15s',
  }),
  btn: (active, color) => ({
    padding: '10px 12px', borderRadius: 8, border: 'none', cursor: 'pointer',
    background: active ? (color || '#e74c3c') : 'rgba(255,255,255,0.08)',
    color: active ? '#fff' : '#ccc', fontSize: 13, fontWeight: 600,
    transition: 'all 0.15s', textAlign: 'center',
  }),
  row: { display: 'flex', gap: 6 },
  input: {
    flex: 1, padding: '8px 10px', borderRadius: 6, border: '1px solid rgba(255,255,255,0.15)',
    background: 'rgba(255,255,255,0.05)', color: '#fff', fontSize: 13, outline: 'none',
  },
  buildItem: {
    padding: '6px 10px', borderRadius: 6, background: 'rgba(255,255,255,0.06)',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    cursor: 'pointer', fontSize: 13,
  },
  deleteBtn: {
    background: 'none', border: 'none', color: '#e74c3c', cursor: 'pointer',
    fontSize: 14, padding: '0 4px',
  },
  stats: { fontSize: 12, color: '#666', textAlign: 'center', marginTop: 'auto', padding: '8px 0' },
  shortcutsHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    cursor: 'pointer', userSelect: 'none', padding: '4px 0',
  },
  shortcutsToggle: {
    fontSize: 11, color: '#666', fontWeight: 600,
  },
  shortcutsList: {
    fontSize: 11, color: '#666', lineHeight: 1.6, marginTop: 6,
    display: 'flex', flexDirection: 'column', gap: 4,
  },
  shortcutItem: {
    display: 'flex', justifyContent: 'space-between', gap: 8,
  },
  shortcutKey: {
    fontFamily: 'monospace', color: '#888', fontWeight: 600, minWidth: '70px', flexShrink: 0,
  },
  shortcutDesc: {
    color: '#555', flex: 1,
  },
}

export default function Sidebar() {
  const selectedColor = useStore((st) => st.selectedColor)
  const selectedSize = useStore((st) => st.selectedSize)
  const selectedRotation = useStore((st) => st.selectedRotation)
  const deleteMode = useStore((st) => st.deleteMode)
  const bricks = useStore((st) => st.bricks)
  const savedBuilds = useStore((st) => st.savedBuilds)
  const { setColor, setSize, toggleDeleteMode, cycleRotation, undo, redo, clearAll, saveBuild, loadBuild, deleteBuild } = useStore()
  const [saveName, setSaveName] = useState('')
  const [showShortcuts, setShowShortcuts] = useState(false)

  const handleSave = () => {
    if (!saveName.trim()) return
    saveBuild(saveName.trim())
    setSaveName('')
  }

  const handleScreenshot = () => {
    const canvas = document.querySelector('canvas')
    if (!canvas) return
    const link = document.createElement('a')
    link.download = `brick-build-${Date.now()}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()
  }

  return (
    <div style={s.sidebar}>
      {/* Colors */}
      <div style={s.section}>
        <div style={s.label}>Color</div>
        <div style={s.colorGrid}>
          {BRICK_COLORS.map((c) => (
            <div
              key={c.hex}
              style={s.colorSwatch(c.hex, selectedColor === c.hex)}
              onClick={() => setColor(c.hex)}
              title={c.name}
            />
          ))}
        </div>
      </div>

      {/* Sizes */}
      <div style={s.section}>
        <div style={s.label}>Size</div>
        <div style={s.sizeGrid}>
          {BRICK_SIZES.map((sz) => (
            <button
              key={sz.label}
              style={s.sizeBtn(selectedSize.label === sz.label)}
              onClick={() => setSize(sz)}
            >
              {sz.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tools */}
      <div style={s.section}>
        <div style={s.label}>Tools</div>
        <button style={s.btn(deleteMode, '#e74c3c')} onClick={toggleDeleteMode}>
          {deleteMode ? 'X  Delete Mode ON' : 'Delete Mode'}
        </button>
        <button style={s.btn(false, '#9b59b6')} onClick={cycleRotation}>
          Rotate ({selectedRotation}°)
        </button>
        <div style={s.row}>
          <button style={{ ...s.btn(false), flex: 1 }} onClick={undo}>Undo</button>
          <button style={{ ...s.btn(false), flex: 1 }} onClick={redo}>Redo</button>
        </div>
        <button style={s.btn(false, '#e67e22')} onClick={clearAll}>Clear All</button>
        <button style={s.btn(false, '#3498db')} onClick={handleScreenshot}>Screenshot</button>
      </div>

      {/* Save / Load */}
      <div style={s.section}>
        <div style={s.label}>Save / Load</div>
        <div style={s.row}>
          <input
            style={s.input}
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            placeholder="Build name..."
            onKeyDown={(e) => e.key === 'Enter' && handleSave()}
          />
          <button style={s.btn(false, '#27ae60')} onClick={handleSave}>Save</button>
        </div>
        {Object.keys(savedBuilds).map((name) => (
          <div key={name} style={s.buildItem} onClick={() => loadBuild(name)}>
            <span>{name}</span>
            <button style={s.deleteBtn} onClick={(e) => { e.stopPropagation(); deleteBuild(name) }}>x</button>
          </div>
        ))}
      </div>

      {/* Stats */}
      <div style={s.stats}>
        {bricks.length} brick{bricks.length !== 1 ? 's' : ''} placed
      </div>

      {/* Help */}
      <div style={{ fontSize: 11, color: '#555', lineHeight: 1.5 }}>
        Click baseplate to place brick<br />
        Click brick to stack on top<br />
        Scroll to zoom, drag to orbit<br />
        Right-click drag to pan
      </div>

      {/* Keyboard Shortcuts */}
      <div style={s.section}>
        <div style={s.shortcutsHeader} onClick={() => setShowShortcuts(!showShortcuts)}>
          <div style={s.label}>Keyboard Shortcuts</div>
          <div style={s.shortcutsToggle}>{showShortcuts ? '−' : '+'}</div>
        </div>
        {showShortcuts && (
          <div style={s.shortcutsList}>
            <div style={s.shortcutItem}>
              <div style={s.shortcutKey}>Ctrl+Z</div>
              <div style={s.shortcutDesc}>Undo</div>
            </div>
            <div style={s.shortcutItem}>
              <div style={s.shortcutKey}>Ctrl+Y</div>
              <div style={s.shortcutDesc}>Redo</div>
            </div>
            <div style={s.shortcutItem}>
              <div style={s.shortcutKey}>D</div>
              <div style={s.shortcutDesc}>Toggle delete</div>
            </div>
            <div style={s.shortcutItem}>
              <div style={s.shortcutKey}>Esc</div>
              <div style={s.shortcutDesc}>Turn off delete</div>
            </div>
            <div style={s.shortcutItem}>
              <div style={s.shortcutKey}>1–8</div>
              <div style={s.shortcutDesc}>Select size</div>
            </div>
            <div style={s.shortcutItem}>
              <div style={s.shortcutKey}>C</div>
              <div style={s.shortcutDesc}>Cycle colors</div>
            </div>
            <div style={s.shortcutItem}>
              <div style={s.shortcutKey}>R</div>
              <div style={s.shortcutDesc}>Cycle rotation</div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
