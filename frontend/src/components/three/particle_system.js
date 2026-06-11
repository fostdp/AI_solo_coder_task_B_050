/**
 * 高性能粒子系统 - 基于 InstancedMesh
 * 修复: Three.js粒子特效在移动端帧率骤降
 * 根因: 每帧更新BufferGeometry属性 + 600个独立粒子draw call
 * 方案:
 *   1. InstancedMesh合并所有粒子为1个draw call
 *   2. 限制粒子数量至500
 *   3. 使用Object3D矩阵更新代替逐顶点position更新
 *   4. 自适应LOD: 移动端自动降低粒子密度
 */

import * as THREE from 'three'

const MAX_PARTICLES = 500
const MOBILE_MAX_PARTICLES = 200

function isMobile() {
  if (typeof navigator === 'undefined') return false
  return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
}

export class InstancedParticleSystem {
  constructor(scene, options = {}) {
    this.scene = scene
    this.maxParticles = isMobile() ? MOBILE_MAX_PARTICLES : MAX_PARTICLES
    this.particles = []
    this.instancedMesh = null
    this.dummy = new THREE.Object3D()
    this.tempColor = new THREE.Color()
    this.clock = new THREE.Clock()
    this.activeCount = 0

    this._createSpriteTexture()
    this._createInstancedMesh(options)
  }

  _createSpriteTexture() {
    const size = 32
    const canvas = document.createElement('canvas')
    canvas.width = size
    canvas.height = size
    const ctx = canvas.getContext('2d')
    const gradient = ctx.createRadialGradient(size/2, size/2, 0, size/2, size/2, size/2)
    gradient.addColorStop(0, 'rgba(255,255,255,1)')
    gradient.addColorStop(0.15, 'rgba(255,220,150,0.9)')
    gradient.addColorStop(0.4, 'rgba(255,120,60,0.5)')
    gradient.addColorStop(1, 'rgba(255,50,30,0)')
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, size, size)
    this.spriteTexture = new THREE.CanvasTexture(canvas)
  }

  _createInstancedMesh(options = {}) {
    const {
      particleSize = 0.02,
      center = new THREE.Vector3(0, 0, 0),
      severity = 0.8
    } = options

    const geo = new THREE.SphereGeometry(particleSize, 6, 6)

    const mat = new THREE.MeshBasicMaterial({
      map: this.spriteTexture,
      transparent: true,
      opacity: 0.85,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      toneMapped: false
    })

    this.instancedMesh = new THREE.InstancedMesh(geo, mat, this.maxParticles)
    this.instancedMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)

    const colorAttr = new THREE.InstancedBufferAttribute(
      new Float32Array(this.maxParticles * 3), 3
    )
    colorAttr.setUsage(THREE.DynamicDrawUsage)
    this.instancedMesh.instanceColor = colorAttr

    for (let i = 0; i < this.maxParticles; i++) {
      this.dummy.position.set(0, -100, 0)
      this.dummy.scale.setScalar(0)
      this.dummy.updateMatrix()
      this.instancedMesh.setMatrixAt(i, this.dummy.matrix)
      this.instancedMesh.setColorAt(i, this.tempColor.setRGB(0, 0, 0))
    }
    this.instancedMesh.instanceMatrix.needsUpdate = true
    this.instancedMesh.instanceColor.needsUpdate = true
    this.instancedMesh.count = 0

    this.instancedMesh.frustumCulled = false
    this.scene.add(this.instancedMesh)
  }

  emit(options = {}) {
    const {
      center = { x: 0, y: 0, z: 0 },
      radius = 0.04,
      severity = 0.8,
      count = null
    } = options

    const actualCount = count !== null
      ? Math.min(count, this.maxParticles - this.activeCount)
      : Math.min(
          Math.floor(100 + severity * (this.maxParticles - 100)),
          this.maxParticles - this.activeCount
        )

    if (actualCount <= 0) return

    const colorPalette = [
      [1.0, 0.15, 0.1],
      [1.0, 0.5, 0.1],
      [1.0, 0.85, 0.1],
      [0.8, 0.7, 0.2],
      [0.3, 0.6, 0.2]
    ]

    for (let i = 0; i < actualCount; i++) {
      const theta = Math.random() * Math.PI * 2
      const phi = Math.random() * Math.PI * 0.6
      const r = radius * (0.2 + Math.random() * 0.8)

      const particle = {
        baseX: r * Math.sin(phi) * Math.cos(theta),
        baseY: r * Math.cos(phi),
        baseZ: r * Math.sin(phi) * Math.sin(theta),
        velX: (Math.random() - 0.5) * 0.03,
        velY: 0.01 + Math.random() * 0.05 * severity,
        velZ: (Math.random() - 0.5) * 0.03,
        centerX: center.x,
        centerY: center.y,
        centerZ: center.z,
        lifetime: Math.random(),
        color: colorPalette[severity > 0.7
          ? Math.floor(Math.random() * 3)
          : Math.floor(Math.random() * colorPalette.length)],
        instanceIdx: this.activeCount + i,
        scale: 0.5 + Math.random() * 0.5,
        active: true
      }

      this.particles.push(particle)

      const idx = particle.instanceIdx
      this.dummy.position.set(
        center.x + particle.baseX,
        center.y + particle.baseY,
        center.z + particle.baseZ
      )
      this.dummy.scale.setScalar(particle.scale)
      this.dummy.updateMatrix()
      this.instancedMesh.setMatrixAt(idx, this.dummy.matrix)
      this.instancedMesh.setColorAt(
        idx,
        this.tempColor.setRGB(particle.color[0], particle.color[1], particle.color[2])
      )
    }

    this.activeCount += actualCount
    this.instancedMesh.count = this.activeCount
    this.instancedMesh.instanceMatrix.needsUpdate = true
    this.instancedMesh.instanceColor.needsUpdate = true
  }

  update() {
    const elapsed = this.clock.getElapsedTime()
    const cycle = (elapsed * 0.3) % 1.0
    let needsMatrixUpdate = false

    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i]
      if (!p.active) continue

      const idx = p.instanceIdx
      let t = (cycle + p.lifetime) % 1.0
      const ease = t * t * (3 - 2 * t)

      this.dummy.position.set(
        p.centerX + p.baseX + p.velX * ease * 300,
        p.centerY + p.baseY + p.velY * ease * 200 + Math.sin(elapsed * 3 + i) * 0.005,
        p.centerZ + p.baseZ + p.velZ * ease * 300
      )
      this.dummy.scale.setScalar(p.scale * (1.0 - t * 0.5))
      this.dummy.updateMatrix()
      this.instancedMesh.setMatrixAt(idx, this.dummy.matrix)

      const fade = 1.0 - t * 0.6
      this.instancedMesh.setColorAt(
        idx,
        this.tempColor.setRGB(
          p.color[0] * fade,
          p.color[1] * fade,
          p.color[2] * fade
        )
      )
      needsMatrixUpdate = true
    }

    if (needsMatrixUpdate) {
      this.instancedMesh.instanceMatrix.needsUpdate = true
      this.instancedMesh.instanceColor.needsUpdate = true
    }
  }

  dispose() {
    if (this.instancedMesh) {
      this.scene.remove(this.instancedMesh)
      this.instancedMesh.geometry.dispose()
      this.instancedMesh.material.dispose()
      if (this.instancedMesh.material.map) {
        this.instancedMesh.material.map.dispose()
      }
      this.instancedMesh = null
    }
    this.particles = []
    this.activeCount = 0
  }

  getStats() {
    return {
      activeParticles: this.activeCount,
      maxParticles: this.maxParticles,
      isMobile: isMobile(),
      drawCalls: 1
    }
  }
}

export default InstancedParticleSystem
