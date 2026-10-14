/**
 * NIRMAN AI — 3D Viewer Component
 * Loads a GLTF file and displays it with orbit controls using React Three Fiber.
 */
import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, useGLTF, Environment, Grid } from '@react-three/drei'

function Building({ url }) {
  const { scene } = useGLTF(url)
  return <primitive object={scene} />
}

export default function Viewer3D({ gltfUrl }) {
  if (!gltfUrl) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm">
        No model loaded. Generate a building to view it here.
      </div>
    )
  }

  return (
    <Canvas
      camera={{ position: [20, 15, 20], fov: 45 }}
      shadows
      style={{ background: '#0f172a' }}
    >
      <ambientLight intensity={0.4} />
      <directionalLight position={[10, 20, 10]} intensity={1.5} castShadow />
      <Suspense fallback={null}>
        <Building url={gltfUrl} />
        <Environment preset="city" />
      </Suspense>
      <Grid
        infiniteGrid
        cellSize={1}
        cellThickness={0.5}
        sectionSize={5}
        sectionThickness={1}
        fadeDistance={80}
        position={[0, -0.01, 0]}
      />
      <OrbitControls makeDefault />
    </Canvas>
  )
}
