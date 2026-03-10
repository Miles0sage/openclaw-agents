'use client';

import { BrickCanvas } from '@/components/BrickCanvas';
import { BrickPalette } from '@/components/BrickPalette';
import { AIAssistant } from '@/components/AIAssistant';
import { TopBar } from '@/components/TopBar';

export default function BuilderPage() {
  return (
    <div className="flex flex-col h-screen bg-gray-100">
      {/* Top Bar */}
      <TopBar />

      {/* Main Content Area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar: Brick Palette */}
        <div className="w-64 overflow-hidden shadow-lg">
          <BrickPalette />
        </div>

        {/* Center: 3D Canvas */}
        <div className="flex-1">
          <BrickCanvas />
        </div>

        {/* Right Sidebar: AI Assistant */}
        <div className="w-96 shadow-lg overflow-hidden">
          <AIAssistant />
        </div>
      </div>
    </div>
  );
}
