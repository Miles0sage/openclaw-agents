import React, { useRef } from 'react'
import { useStore } from '../store'

const GRID_SIZE = 32
const UNIT = 1
const BRICK_HEIGHT = 1.2

export default function Baseplate() {
  const placeBrick = useStore((s) => s.placeBrick)
  const deleteMode = useStore((s) => s.deleteMode)
  const selectedSize = useStore((s) => s.selectedSize)
  const setHoverPosition = useStore((s) => s.setHoverPosition)
  const ref = useRef()

  const handleClick = (e) => {
    if (deleteMode) return
    e.stopPropagation()
    const point = e.point
    // Snap to grid
    const x = Math.round(point.x)
    const z = Math.round(point.z)
    const y = BRICK_HEIGHT / 2
    placeBrick([x, y, z])
  }

  const handlePointerMove = (e) => {
    e.stopPropagation()
    const point = e.point
    // Snap to grid
    const x = Math.round(point.x)
    const z = Math.round(point.z)
    const y = BRICK_HEIGHT / 2
    setHoverPosition([x, y, z])
  }

  const handlePointerLeave = (e) => {
    e.stopPropagation()
    setHoverPosition(null)
  }

  return (
    <group>
      {/* Main baseplate */}
      <mesh
        ref={ref}
        rotation={[-Math.PI / 2, 0, 0]}
        position={[GRID_SIZE / 2 - 0.5, -0.05, GRID_SIZE / 2 - 0.5]}
        receiveShadow
        onClick={handleClick}
        onPointerMove={handlePointerMove}
        onPointerLeave={handlePointerLeave}
      >
        <planeGeometry args={[GRID_SIZE, GRID_SIZE]} />
        <meshStandardMaterial color="#2d5a27" roughness={0.8} />
      </mesh>
      {/* Grid lines */}
      <gridHelper
        args={[GRID_SIZE, GRID_SIZE, '#3a7a33', '#3a7a33']}
        position={[GRID_SIZE / 2 - 0.5, 0, GRID_SIZE / 2 - 0.5]}
      />
    </group>
  )
}
