import React, { useEffect } from 'react'
import Scene from './components/Scene'
import Sidebar from './components/Sidebar'
import AIPanel from './components/AIPanel'
import { useStore, BRICK_SIZES, BRICK_COLORS } from './store'

const styles = {
  container: {
    display: 'flex',
    height: '100vh',
    width: '100vw',
    background: '#1a1a2e',
  },
  viewport: {
    flex: 1,
    position: 'relative',
  },
  title: {
    position: 'absolute',
    top: 12,
    left: '50%',
    transform: 'translateX(-50%)',
    color: '#fff',
    fontSize: 18,
    fontWeight: 700,
    letterSpacing: 2,
    textTransform: 'uppercase',
    opacity: 0.5,
    pointerEvents: 'none',
    zIndex: 10,
  },
}

export default function App() {
  const { undo, redo, toggleDeleteMode, deleteMode, setSize, setColor, selectedColor, cycleRotation } = useStore()

  useEffect(() => {
    const handleKeyDown = (e) => {
      // Don't fire shortcuts when typing in text inputs
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
        return
      }

      // Ctrl+Z: Undo
      if (e.ctrlKey && e.key === 'z' && !e.shiftKey) {
        e.preventDefault()
        undo()
        return
      }

      // Ctrl+Y or Ctrl+Shift+Z: Redo
      if ((e.ctrlKey && e.key === 'y') || (e.ctrlKey && e.shiftKey && e.key === 'Z')) {
        e.preventDefault()
        redo()
        return
      }

      // R: Cycle rotation
      if (e.key === 'r' || e.key === 'R') {
        e.preventDefault()
        cycleRotation()
        return
      }

      // D: Toggle delete mode
      if (e.key === 'd' || e.key === 'D') {
        e.preventDefault()
        toggleDeleteMode()
        return
      }

      // Escape: Turn off delete mode
      if (e.key === 'Escape' && deleteMode) {
        e.preventDefault()
        toggleDeleteMode()
        return
      }

      // 1-8: Select brick size (maps to BRICK_SIZES array index)
      if (e.key >= '1' && e.key <= '8') {
        const index = parseInt(e.key) - 1
        if (index < BRICK_SIZES.length) {
          e.preventDefault()
          setSize(BRICK_SIZES[index])
          return
        }
      }

      // C: Cycle through colors
      if (e.key === 'c' || e.key === 'C') {
        e.preventDefault()
        const currentIndex = BRICK_COLORS.findIndex((c) => c.hex === selectedColor)
        const nextIndex = (currentIndex + 1) % BRICK_COLORS.length
        setColor(BRICK_COLORS[nextIndex].hex)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [undo, redo, toggleDeleteMode, deleteMode, setSize, setColor, selectedColor, cycleRotation])

  return (
    <div style={styles.container}>
      <Sidebar />
      <div style={styles.viewport}>
        <div style={styles.title}>Brick Builder</div>
        <Scene />
      </div>
      <AIPanel />
    </div>
  )
}
