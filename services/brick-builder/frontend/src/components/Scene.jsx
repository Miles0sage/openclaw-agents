import React, { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Environment, ContactShadows } from '@react-three/drei'
import Baseplate from './Baseplate'
import LegoBrick from './LegoBrick'
import GhostBrick from './GhostBrick'
import { useStore } from '../store'

function BrickWorld() {
  const bricks = useStore((s) => s.bricks)
  return (
    <>
      <Baseplate />
      <GhostBrick />
      {bricks.map((brick) => (
        <LegoBrick key={brick.id} brick={brick} />
      ))}
    </>
  )
}

export default function Scene() {
  return (
    <Canvas
      shadows
      camera={{ position: [20, 18, 20], fov: 50 }}
      style={{ width: '100%', height: '100%' }}
      gl={{ preserveDrawingBuffer: true, antialias: true }}
    >
      <color attach="background" args={['#16213e']} />
      <fog attach="fog" args={['#16213e', 40, 80]} />

      {/* Lighting */}
      <ambientLight intensity={0.4} />
      <directionalLight
        position={[15, 25, 15]}
        intensity={1.2}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-far={60}
        shadow-camera-left={-20}
        shadow-camera-right={20}
        shadow-camera-top={20}
        shadow-camera-bottom={-20}
      />
      <directionalLight position={[-10, 10, -10]} intensity={0.3} />

      <Suspense fallback={null}>
        <BrickWorld />
        <ContactShadows
          position={[15, -0.04, 15]}
          opacity={0.4}
          scale={40}
          blur={2}
          far={20}
        />
      </Suspense>

      <OrbitControls
        target={[16, 0, 16]}
        maxPolarAngle={Math.PI / 2.1}
        minDistance={5}
        maxDistance={50}
        enableDamping
        dampingFactor={0.08}
      />
    </Canvas>
  )
}
