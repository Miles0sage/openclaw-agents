'use client';

import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useRef, useEffect } from 'react';
import * as THREE from 'three';
import { useBrickStore, type Brick } from '@/lib/store';

interface BrickProps {
  brick: Brick;
  onSelect?: (id: string) => void;
  onClick?: () => void;
}

function BrickObject({ brick, onSelect, onClick }: BrickProps) {
  const meshRef = useRef<THREE.Mesh>(null);

  const getDimensions = (type: string): [number, number, number] => {
    const dimensions: Record<string, [number, number, number]> = {
      'brick-1x1': [0.8, 1.2, 0.8],
      'brick-1x2': [0.8, 1.2, 1.6],
      'brick-2x2': [1.6, 1.2, 1.6],
      'brick-2x4': [1.6, 1.2, 3.2],
      'brick-2x3': [1.6, 1.2, 2.4],
    };
    return dimensions[type] || [1, 1, 1];
  };

  const dimensions = getDimensions(brick.type);

  const handleClick = (e: any) => {
    e.stopPropagation();
    onSelect?.(brick.id);
    onClick?.();
  };

  return (
    <mesh
      ref={meshRef}
      position={brick.position}
      rotation={brick.rotation}
      onClick={handleClick}
      castShadow
      receiveShadow
    >
      <boxGeometry args={dimensions} />
      <meshStandardMaterial
        color={brick.color}
        metalness={0.2}
        roughness={0.8}
      />
    </mesh>
  );
}

function GridCanvas() {
  const { camera } = useThree();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const raycasterRef = useRef(new THREE.Raycaster());
  const mouseRef = useRef(new THREE.Vector2());

  const bricks = useBrickStore((state) => state.bricks);
  const addBrick = useBrickStore((state) => state.addBrick);
  const selectedBrickType = useBrickStore((state) => state.selectedBrickType);
  const selectedColor = useBrickStore((state) => state.selectedColor);

  useEffect(() => {
    const handleCanvasClick = (event: MouseEvent) => {
      if (!canvasRef.current) return;

      const canvas = canvasRef.current;
      const rect = canvas.getBoundingClientRect();
      mouseRef.current.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      mouseRef.current.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycasterRef.current.setFromCamera(mouseRef.current, camera);

      // Create a plane at z=0 to detect clicks for placement
      const planeGeometry = new THREE.PlaneGeometry(100, 100);
      const plane = new THREE.Mesh(planeGeometry);
      plane.position.z = 0;

      const intersects = raycasterRef.current.intersectObject(plane);

      if (intersects.length > 0) {
        const point = intersects[0].point;
        const gridSize = 0.8;
        const snappedX = Math.round(point.x / gridSize) * gridSize;
        const snappedY = Math.round(point.y / gridSize) * gridSize;

        // Check if there's already a brick at this position
        const hasExistingBrick = bricks.some(
          (brick) =>
            Math.abs(brick.position[0] - snappedX) < 0.4 &&
            Math.abs(brick.position[1] - snappedY) < 0.4
        );

        if (!hasExistingBrick) {
          const newBrick: Brick = {
            id: `brick-${Date.now()}-${Math.random()}`,
            type: selectedBrickType as any,
            position: [snappedX, snappedY, 0],
            rotation: [0, 0, 0],
            color: selectedColor,
          };

          addBrick(newBrick);
        }
      }
    };

    const canvas = canvasRef.current;
    if (canvas) {
      canvas.addEventListener('click', handleCanvasClick);
      return () => canvas.removeEventListener('click', handleCanvasClick);
    }
  }, [camera, bricks, addBrick, selectedBrickType, selectedColor]);

  // Store canvas ref in a way accessible to event listeners
  useEffect(() => {
    const canvas = document.querySelector('canvas');
    if (canvas) {
      canvasRef.current = canvas;
    }
  }, []);

  return null;
}

export function BrickCanvas() {
  const bricks = useBrickStore((state) => state.bricks);
  const removeBrick = useBrickStore((state) => state.removeBrick);

  return (
    <div className="w-full h-full bg-gradient-to-br from-gray-100 to-gray-200">
      <Canvas
        camera={{ position: [0, 0, 15], fov: 50 }}
        gl={{ antialias: true, alpha: true }}
        shadows
      >
        <ambientLight intensity={0.6} />
        <directionalLight
          position={[10, 15, 10]}
          intensity={1}
          castShadow
          shadow-mapSize-width={2048}
          shadow-mapSize-height={2048}
        />

        <gridHelper args={[20, 20]} />

        {bricks.map((brick) => (
          <BrickObject
            key={brick.id}
            brick={brick}
            onClick={() => removeBrick(brick.id)}
          />
        ))}

        <OrbitControls
          autoRotate={false}
          minZoom={5}
          maxZoom={50}
          enableDamping
          dampingFactor={0.05}
        />

        <GridCanvas />
      </Canvas>
    </div>
  );
}
