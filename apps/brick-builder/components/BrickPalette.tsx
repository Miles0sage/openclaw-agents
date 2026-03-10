'use client';

import { useBrickStore } from '@/lib/store';
import { useState } from 'react';

const BRICK_TYPES = [
  { id: 'brick-1x1', label: '1x1', width: 'w-12', height: 'h-8' },
  { id: 'brick-1x2', label: '1x2', width: 'w-12', height: 'h-16' },
  { id: 'brick-2x2', label: '2x2', width: 'w-24', height: 'h-24' },
  { id: 'brick-2x4', label: '2x4', width: 'w-24', height: 'h-48' },
  { id: 'brick-2x3', label: '2x3', width: 'w-24', height: 'h-36' },
];

const LEGO_COLORS = [
  { name: 'Red', hex: '#DC143C' },
  { name: 'Blue', hex: '#0055BF' },
  { name: 'Yellow', hex: '#F7BE16' },
  { name: 'Green', hex: '#239B24' },
  { name: 'White', hex: '#FFFFFF' },
  { name: 'Black', hex: '#05131D' },
  { name: 'Orange', hex: '#FE8500' },
  { name: 'Tan', hex: '#D2B48C' },
  { name: 'Brown', hex: '#5C4033' },
  { name: 'Gray', hex: '#9D9D9D' },
  { name: 'Purple', hex: '#A020F0' },
  { name: 'Pink', hex: '#F03C78' },
];

export function BrickPalette() {
  const selectedBrickType = useBrickStore((state) => state.selectedBrickType);
  const selectedColor = useBrickStore((state) => state.selectedColor);
  const selectBrickType = useBrickStore((state) => state.selectBrickType);
  const selectColor = useBrickStore((state) => state.selectColor);
  const [colorInputValue, setColorInputValue] = useState(selectedColor);

  return (
    <div className="flex flex-col h-full bg-slate-900 text-white p-4 overflow-y-auto border-r border-slate-700">
      <h2 className="text-xl font-bold mb-4">Brick Palette</h2>

      {/* Brick Types */}
      <div className="mb-6">
        <h3 className="text-sm font-semibold text-slate-300 mb-3 uppercase tracking-wider">
          Brick Types
        </h3>
        <div className="space-y-2">
          {BRICK_TYPES.map((brickType) => (
            <button
              key={brickType.id}
              onClick={() => selectBrickType(brickType.id)}
              className={`w-full px-3 py-2 rounded text-sm font-medium transition ${
                selectedBrickType === brickType.id
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 hover:bg-slate-600 text-slate-100'
              }`}
            >
              {brickType.label}
            </button>
          ))}
        </div>
      </div>

      {/* Color Picker */}
      <div className="mb-6">
        <h3 className="text-sm font-semibold text-slate-300 mb-3 uppercase tracking-wider">
          Color
        </h3>
        <div className="grid grid-cols-4 gap-2">
          {LEGO_COLORS.map((color) => (
            <button
              key={color.hex}
              onClick={() => {
                selectColor(color.hex);
                setColorInputValue(color.hex);
              }}
              className={`w-full aspect-square rounded border-2 transition ${
                selectedColor === color.hex
                  ? 'border-white shadow-lg'
                  : 'border-slate-600 hover:border-slate-500'
              }`}
              style={{ backgroundColor: color.hex }}
              title={color.name}
            />
          ))}
        </div>
      </div>

      {/* Custom Color */}
      <div className="mb-6">
        <label className="text-sm font-semibold text-slate-300 block mb-2">
          Custom Color
        </label>
        <div className="flex gap-2">
          <input
            type="color"
            value={colorInputValue}
            onChange={(e) => {
              setColorInputValue(e.target.value);
              selectColor(e.target.value);
            }}
            className="w-12 h-10 rounded cursor-pointer"
          />
          <input
            type="text"
            value={colorInputValue}
            onChange={(e) => {
              setColorInputValue(e.target.value);
              selectColor(e.target.value);
            }}
            className="flex-1 px-2 py-1 rounded bg-slate-700 text-white text-sm font-mono"
            placeholder="#RRGGBB"
          />
        </div>
      </div>

      {/* Info */}
      <div className="mt-auto pt-4 border-t border-slate-700 text-xs text-slate-400">
        <p className="mb-2">
          <strong>Click grid</strong> to place brick
        </p>
        <p>
          <strong>Click brick</strong> to delete
        </p>
      </div>
    </div>
  );
}
