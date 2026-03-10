import React, { useRef, useState } from 'react'
import { useStore } from '../store'

const UNIT = 1
const BRICK_HEIGHT = 1.2
const STUD_HEIGHT = 0.22
const STUD_RADIUS = 0.3

function Stud({ position }) {
  return (
    <mesh position={position} castShadow>
      <cylinderGeometry args={[STUD_RADIUS, STUD_RADIUS, STUD_HEIGHT, 16]} />
      <meshStandardMaterial color="inherit" />
    </mesh>
  )
}

export default function LegoBrick({ brick }) {
  const { id, position, color, width, depth, rotation } = brick
  const deleteMode = useStore((s) => s.deleteMode)
  const deleteBrick = useStore((s) => s.deleteBrick)
  const placeBrick = useStore((s) => s.placeBrick)
  const selectedSize = useStore((s) => s.selectedSize)
  const [hovered, setHovered] = useState(false)

  const w = width * UNIT
  const d = depth * UNIT
  const h = BRICK_HEIGHT

  // Generate stud positions
  const studs = []
  for (let sx = 0; sx < width; sx++) {
    for (let sz = 0; sz < depth; sz++) {
      studs.push([
        (sx - (width - 1) / 2) * UNIT,
        h / 2 + STUD_HEIGHT / 2,
        (sz - (depth - 1) / 2) * UNIT,
      ])
    }
  }

  const handleClick = (e) => {
    e.stopPropagation()
    if (deleteMode) {
      deleteBrick(id)
    } else {
      // Place a new brick on top
      const newY = position[1] + BRICK_HEIGHT
      const newX = position[0]
      const newZ = position[2]
      placeBrick([newX, newY, newZ])
    }
  }

  return (
    <group
      position={position}
      rotation={[0, (rotation || 0) * Math.PI / 180, 0]}
      onClick={handleClick}
      onPointerOver={(e) => { e.stopPropagation(); setHovered(true); document.body.style.cursor = deleteMode ? 'crosshair' : 'pointer' }}
      onPointerOut={(e) => { setHovered(false); document.body.style.cursor = 'default' }}
    >
      {/* Main brick body */}
      <mesh castShadow receiveShadow>
        <boxGeometry args={[w - 0.05, h, d - 0.05]} />
        <meshStandardMaterial
          color={hovered && deleteMode ? '#ff4444' : color}
          roughness={0.3}
          metalness={0.1}
          emissive={hovered && !deleteMode ? color : '#000000'}
          emissiveIntensity={hovered && !deleteMode ? 0.15 : 0}
        />
      </mesh>
      {/* Studs */}
      {studs.map((pos, i) => (
        <mesh key={i} position={pos} castShadow>
          <cylinderGeometry args={[STUD_RADIUS, STUD_RADIUS, STUD_HEIGHT, 16]} />
          <meshStandardMaterial
            color={hovered && deleteMode ? '#ff4444' : color}
            roughness={0.3}
            metalness={0.1}
          />
        </mesh>
      ))}
    </group>
  )
}
