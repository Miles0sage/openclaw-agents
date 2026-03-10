# 🧱 Brick Builder

An AI-assisted 3D LEGO building application built with React, Three.js, and TypeScript. This is a showcase project for the OpenClaw platform demonstrating the power of AI-enhanced creative tools.

## Features

- **3D Visualization** - Real-time 3D rendering using Three.js with interactive camera controls
- **Grid Snapping** - Bricks automatically snap to a grid for perfect alignment
- **AI Assistant** - Chat with an AI that suggests brick placements based on text descriptions
- **Flexible Palette** - 12 authentic LEGO colors plus custom color picker
- **Undo/Redo** - Full history support with unlimited undo and redo
- **Save & Export** - Save your builds locally as JSON or export for sharing
- **Multiple Brick Types** - Support for 1x1, 1x2, 2x2, 2x3, and 2x4 bricks

## Getting Started

### Prerequisites

- Node.js 18+
- npm or yarn

### Installation

```bash
cd ./apps/brick-builder
npm install
```

### Development

```bash
npm run dev
```

The app will start at `http://localhost:3000` (or the next available port).

### Building for Production

```bash
npm run build
npm run start
```

## Project Structure

```
./apps/brick-builder/
├── app/
│   ├── page.tsx              # Landing page
│   ├── builder/
│   │   └── page.tsx          # Main builder interface
│   ├── layout.tsx            # Root layout
│   └── globals.css           # Global styles
├── components/
│   ├── BrickCanvas.tsx       # Three.js 3D canvas with brick rendering
│   ├── BrickPalette.tsx      # Brick type and color selector
│   ├── AIAssistant.tsx       # Chat interface for AI suggestions
│   └── TopBar.tsx            # Header with controls and file operations
├── lib/
│   └── store.ts              # Zustand store for application state
├── public/                   # Static assets
├── package.json
├── tsconfig.json
└── tailwind.config.ts
```

## How to Use

### Building with Bricks

1. Click on a brick type in the left sidebar to select it
2. Choose a color from the palette
3. Click on the grid canvas to place bricks
4. Click on a brick to delete it
5. Use Undo/Redo buttons to correct mistakes

### AI Suggestions

1. Type a description in the chat panel (e.g., "build a house", "create a tower")
2. The AI will suggest and place bricks accordingly
3. The AI recognizes keywords like: house, tower, wall, fence, add

### Saving Your Work

- **Save** - Downloads your build as a `.json` file locally
- **Load** - Loads a previously saved build from your computer
- **Export** - Creates a detailed export with statistics

## Technology Stack

- **Framework**: Next.js 16 with TypeScript
- **3D Rendering**: Three.js + React Three Fiber
- **UI Components**: React + Tailwind CSS
- **State Management**: Zustand
- **HTTP Client**: Axios

## Architecture Notes

### Store (Zustand)

The app uses a centralized Zustand store that manages:
- `bricks[]` - Array of placed bricks with position, type, rotation, color
- `selectedBrickType` - Currently selected brick type
- `selectedColor` - Currently selected color
- `history[]` - Undo/redo history with snapshots

### Brick Canvas

The Three.js canvas:
- Uses OrbitControls for camera manipulation
- Grid helper for visual guidance
- Ray casting to detect clicks on the plane (z=0)
- Automatically snaps new bricks to 0.8 unit grid
- Prevents placing bricks on top of existing ones

### AI Assistant

The chat interface:
- Sends user messages as prompts
- Parses simple patterns to generate brick placements
- Plans for future OpenClaw gateway integration at `/api/chat`

## Future Enhancements

- Integration with OpenClaw gateway for advanced AI suggestions
- Rebrickable API integration for accurate LEGO pieces
- Save builds to cloud
- Multi-user collaboration
- Import/export to standard LEGO formats
- Build instructions generation
- Inventory tracking

## Development Notes

### Adding New Brick Types

Edit the `BRICK_TYPES` array in `components/BrickPalette.tsx` and the `getDimensions()` function in `components/BrickCanvas.tsx`.

### Styling

The app uses Tailwind CSS. Color scheme is dark slate sidebar with light canvas and white chat panel for visual separation.

### Testing

To verify the app works:

```bash
npm run build    # Should complete without errors
npm run dev      # Should start on port 3000 or 3001
```

## Contributing

This project is part of OpenClaw. For architectural decisions or major changes, coordinate with the team.

## License

MIT - Part of the OpenClaw project ecosystem
