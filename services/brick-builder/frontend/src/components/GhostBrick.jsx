import React from 'react'
import { useStore } from '../store'

const BRICK_HEIGHT = 1.2

export default function GhostBrick() {
  const hoverPosition = useStore((s) => s.hoverPosition)
  const selectedSize = useStore((s) => s.selectedSize)
  const selectedColor = useStore((s) => s.selectedColor)
  const deleteMode = useStore((s) => s.deleteMode)

  if (!hoverPosition || deleteMode) return null

  const { w, d } = selectedSize

  return (
    <mesh position={hoverPosition}>
      <boxGeometry args={[w, BRICK_HEIGHT, d]} />
      <meshStandardMaterial
        color={selectedColor}
        transparent
        opacity={0.35}
        depthWrite={false}
      />
    </mesh>
  )
}
