import { create } from 'zustand'

const UNIT = 1
const BRICK_HEIGHT = 1.2

export const BRICK_COLORS = [
  { name: 'Red', hex: '#DC0004' },
  { name: 'Blue', hex: '#0057A8' },
  { name: 'Yellow', hex: '#FFD700' },
  { name: 'Green', hex: '#00852B' },
  { name: 'White', hex: '#F4F4F4' },
  { name: 'Black', hex: '#1B1B1B' },
  { name: 'Orange', hex: '#FF7E14' },
  { name: 'Lime', hex: '#A5CA18' },
  { name: 'Dark Blue', hex: '#00325A' },
  { name: 'Brown', hex: '#583927' },
  { name: 'Light Gray', hex: '#A0A19F' },
  { name: 'Pink', hex: '#FC97AC' },
]

export const BRICK_SIZES = [
  { label: '1x1', w: 1, d: 1 },
  { label: '1x2', w: 1, d: 2 },
  { label: '1x3', w: 1, d: 3 },
  { label: '1x4', w: 1, d: 4 },
  { label: '2x2', w: 2, d: 2 },
  { label: '2x3', w: 2, d: 3 },
  { label: '2x4', w: 2, d: 4 },
  { label: '2x6', w: 2, d: 6 },
]

let nextId = 1

export const useStore = create((set, get) => ({
  bricks: [],
  selectedColor: BRICK_COLORS[0].hex,
  selectedSize: BRICK_SIZES[4], // 2x2 default
  selectedRotation: 0,
  deleteMode: false,
  history: [],
  future: [],
  savedBuilds: JSON.parse(localStorage.getItem('brick-builds') || '{}'),
  aiLoading: false,
  aiResult: null,
  hoverPosition: null,

  setColor: (color) => set({ selectedColor: color }),
  setSize: (size) => set({ selectedSize: size }),
  setRotation: (r) => set({ selectedRotation: r }),
  cycleRotation: () => set((s) => ({ selectedRotation: (s.selectedRotation + 90) % 360 })),
  toggleDeleteMode: () => set((s) => ({ deleteMode: !s.deleteMode })),
  setHoverPosition: (pos) => set({ hoverPosition: pos }),

  placeBrick: (position) => {
    const state = get()
    if (state.deleteMode) return
    const { selectedColor, selectedSize, selectedRotation } = state
    const brick = {
      id: nextId++,
      position: [...position],
      color: selectedColor,
      width: selectedSize.w,
      depth: selectedSize.d,
      rotation: selectedRotation,
    }
    set((s) => ({
      bricks: [...s.bricks, brick],
      history: [...s.history, s.bricks],
      future: [],
    }))
  },

  deleteBrick: (id) => {
    set((s) => ({
      bricks: s.bricks.filter((b) => b.id !== id),
      history: [...s.history, s.bricks],
      future: [],
    }))
  },

  undo: () => {
    const { history, bricks } = get()
    if (history.length === 0) return
    const prev = history[history.length - 1]
    set({
      bricks: prev,
      history: history.slice(0, -1),
      future: [bricks, ...get().future],
    })
  },

  redo: () => {
    const { future, bricks } = get()
    if (future.length === 0) return
    const next = future[0]
    set({
      bricks: next,
      history: [...get().history, bricks],
      future: future.slice(1),
    })
  },

  clearAll: () => {
    set((s) => ({
      bricks: [],
      history: [...s.history, s.bricks],
      future: [],
    }))
  },

  saveBuild: (name) => {
    const builds = { ...get().savedBuilds, [name]: get().bricks }
    localStorage.setItem('brick-builds', JSON.stringify(builds))
    set({ savedBuilds: builds })
  },

  loadBuild: (name) => {
    const builds = get().savedBuilds
    if (builds[name]) {
      set((s) => ({
        bricks: builds[name],
        history: [...s.history, s.bricks],
        future: [],
      }))
      nextId = Math.max(...builds[name].map((b) => b.id), 0) + 1
    }
  },

  deleteBuild: (name) => {
    const builds = { ...get().savedBuilds }
    delete builds[name]
    localStorage.setItem('brick-builds', JSON.stringify(builds))
    set({ savedBuilds: builds })
  },

  setAiLoading: (v) => set({ aiLoading: v }),
  setAiResult: (v) => set({ aiResult: v }),

  loadBricksFromAI: (bricks) => {
    const mapped = bricks.map((b, i) => ({
      id: nextId++,
      position: Array.isArray(b.position) ? b.position : [b.x || 0, b.y || 0, b.z || 0],
      color: b.color || BRICK_COLORS[i % BRICK_COLORS.length].hex,
      width: b.width || 2,
      depth: b.depth || 2,
      rotation: b.rotation || 0,
    }))
    set((s) => ({
      bricks: [...s.bricks, ...mapped],
      history: [...s.history, s.bricks],
      future: [],
    }))
  },
}))
