import { create } from 'zustand';

export interface Brick {
  id: string;
  type: 'brick-1x1' | 'brick-1x2' | 'brick-2x2' | 'brick-2x4' | 'brick-2x3';
  position: [number, number, number];
  rotation: [number, number, number];
  color: string;
}

interface BrickBuilderStore {
  bricks: Brick[];
  selectedBrickType: string;
  selectedColor: string;
  history: Brick[][];
  historyIndex: number;

  addBrick: (brick: Brick) => void;
  removeBrick: (id: string) => void;
  updateBrick: (id: string, updates: Partial<Brick>) => void;
  selectBrickType: (type: string) => void;
  selectColor: (color: string) => void;
  undo: () => void;
  redo: () => void;
  clear: () => void;
  setBricks: (bricks: Brick[]) => void;
}

export const useBrickStore = create<BrickBuilderStore>((set, get) => ({
  bricks: [],
  selectedBrickType: 'brick-2x2',
  selectedColor: '#DC143C', // LEGO Red
  history: [[]],
  historyIndex: 0,

  addBrick: (brick: Brick) => {
    set((state) => {
      const newBricks = [...state.bricks, brick];
      const newHistory = state.history.slice(0, state.historyIndex + 1);
      newHistory.push(newBricks);
      return {
        bricks: newBricks,
        history: newHistory,
        historyIndex: newHistory.length - 1,
      };
    });
  },

  removeBrick: (id: string) => {
    set((state) => {
      const newBricks = state.bricks.filter((b) => b.id !== id);
      const newHistory = state.history.slice(0, state.historyIndex + 1);
      newHistory.push(newBricks);
      return {
        bricks: newBricks,
        history: newHistory,
        historyIndex: newHistory.length - 1,
      };
    });
  },

  updateBrick: (id: string, updates: Partial<Brick>) => {
    set((state) => {
      const newBricks = state.bricks.map((b) =>
        b.id === id ? { ...b, ...updates } : b
      );
      const newHistory = state.history.slice(0, state.historyIndex + 1);
      newHistory.push(newBricks);
      return {
        bricks: newBricks,
        history: newHistory,
        historyIndex: newHistory.length - 1,
      };
    });
  },

  selectBrickType: (type: string) => {
    set({ selectedBrickType: type });
  },

  selectColor: (color: string) => {
    set({ selectedColor: color });
  },

  undo: () => {
    set((state) => {
      if (state.historyIndex > 0) {
        const newIndex = state.historyIndex - 1;
        return {
          bricks: state.history[newIndex],
          historyIndex: newIndex,
        };
      }
      return state;
    });
  },

  redo: () => {
    set((state) => {
      if (state.historyIndex < state.history.length - 1) {
        const newIndex = state.historyIndex + 1;
        return {
          bricks: state.history[newIndex],
          historyIndex: newIndex,
        };
      }
      return state;
    });
  },

  clear: () => {
    set({
      bricks: [],
      history: [[]],
      historyIndex: 0,
    });
  },

  setBricks: (bricks: Brick[]) => {
    set((state) => {
      const newHistory = state.history.slice(0, state.historyIndex + 1);
      newHistory.push(bricks);
      return {
        bricks,
        history: newHistory,
        historyIndex: newHistory.length - 1,
      };
    });
  },
}));
