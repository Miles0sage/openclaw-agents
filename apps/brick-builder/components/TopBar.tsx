'use client';

import { useBrickStore } from '@/lib/store';
import { useState } from 'react';

export function TopBar() {
  const bricks = useBrickStore((state) => state.bricks);
  const undo = useBrickStore((state) => state.undo);
  const redo = useBrickStore((state) => state.redo);
  const clear = useBrickStore((state) => state.clear);
  const historyIndex = useBrickStore((state) => state.historyIndex);
  const history = useBrickStore((state) => state.history);
  const [fileName, setFileName] = useState('my-build');

  const handleSave = () => {
    const data = {
      bricks,
      name: fileName,
      timestamp: new Date().toISOString(),
    };
    const json = JSON.stringify(data, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${fileName}.json`;
    a.click();
  };

  const handleLoad = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = (e: any) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (event: any) => {
        try {
          const data = JSON.parse(event.target.result);
          useBrickStore.setState({
            bricks: data.bricks,
            history: [data.bricks],
            historyIndex: 0,
          });
        } catch (error) {
          alert('Error loading file');
        }
      };
      reader.readAsText(file);
    };
    input.click();
  };

  const handleExport = () => {
    const data = {
      format: 'brick-builder-v1',
      bricks,
      stats: {
        totalBricks: bricks.length,
        colors: [...new Set(bricks.map((b) => b.color))],
        types: [...new Set(bricks.map((b) => b.type))],
      },
      timestamp: new Date().toISOString(),
    };
    const json = JSON.stringify(data, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${fileName}-export.json`;
    a.click();
  };

  return (
    <div className="flex items-center justify-between bg-gradient-to-r from-slate-800 to-slate-900 text-white px-6 py-4 border-b border-slate-700 shadow-lg">
      {/* Left: Title and Stats */}
      <div className="flex items-center gap-6">
        <div>
          <h1 className="text-2xl font-bold">🧱 Brick Builder</h1>
          <p className="text-sm text-slate-300">
            {bricks.length} brick{bricks.length !== 1 ? 's' : ''}
          </p>
        </div>
      </div>

      {/* Center: File Name */}
      <div className="flex-1 mx-6">
        <input
          type="text"
          value={fileName}
          onChange={(e) => setFileName(e.target.value)}
          className="px-3 py-2 rounded bg-slate-700 text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
          placeholder="Build name"
        />
      </div>

      {/* Right: Controls */}
      <div className="flex items-center gap-2">
        {/* Undo/Redo */}
        <button
          onClick={undo}
          disabled={historyIndex <= 0}
          className="px-3 py-2 rounded bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-500 transition text-sm font-medium"
          title="Undo (Ctrl+Z)"
        >
          ↶ Undo
        </button>
        <button
          onClick={redo}
          disabled={historyIndex >= history.length - 1}
          className="px-3 py-2 rounded bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:text-slate-500 transition text-sm font-medium"
          title="Redo (Ctrl+Y)"
        >
          ↷ Redo
        </button>

        {/* Divider */}
        <div className="w-px h-6 bg-slate-600 mx-2"></div>

        {/* File Operations */}
        <button
          onClick={handleSave}
          className="px-3 py-2 rounded bg-emerald-700 hover:bg-emerald-600 transition text-sm font-medium"
          title="Save to JSON"
        >
          💾 Save
        </button>
        <button
          onClick={handleLoad}
          className="px-3 py-2 rounded bg-blue-700 hover:bg-blue-600 transition text-sm font-medium"
          title="Load from JSON"
        >
          📂 Load
        </button>
        <button
          onClick={handleExport}
          className="px-3 py-2 rounded bg-purple-700 hover:bg-purple-600 transition text-sm font-medium"
          title="Export as JSON"
        >
          📤 Export
        </button>

        {/* Divider */}
        <div className="w-px h-6 bg-slate-600 mx-2"></div>

        {/* Clear */}
        <button
          onClick={() => {
            if (confirm('Clear all bricks? This cannot be undone.')) {
              clear();
            }
          }}
          className="px-3 py-2 rounded bg-red-700 hover:bg-red-600 transition text-sm font-medium"
          title="Clear all"
        >
          🗑️ Clear
        </button>
      </div>
    </div>
  );
}
