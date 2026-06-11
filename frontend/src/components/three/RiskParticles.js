import * as THREE from 'three'
import { InstancedParticleSystem } from './particle_system.js'

/**
 * 风险区与爆发粒子模块
 * 负责风险区脉冲光效、冲击波、爆发粒子系统
 *
 * 用法:
 *   const rp = new RiskParticles(scene, camera)
 *   rp.addRiskZone({ center: {x:0, y:0, z:0}, radius: 0.05, severity: 0.8 })
 *   rp.addEruption({ center: {x:0, y:0.1, z:0}, severity: 0.9 })
 *   rp.update(elapsed)
 */
export class RiskParticles {
  constructor(scene, camera, options = {}) {
    this.scene = scene
    this.camera = camera
    this.options = {
      maxRiskZones: 20,
      ...options
    }

    this.riskZones = []
    this.eruptionParticles = []
    this.instancedParticleSystems = []
    this.riskMaterials = []
    this._clock = new THREE.Clock()
    this._startedAt = 0
  }

  /**
   * 添加一个风险区脉冲光效
   */
  addRiskZone(options = {}) {
    const {
      center = { x: 0, y: 0, z: 0 },
      radius = 0.05,
      severity = 0.5,
      zoneId = `Z${this.riskZones.length + 1}`,
      showLabel = true
    } = options

    const zoneGroup = new THREE.Group()
    const intensity = Math.min(1, 0.3 + severity * 0.7)

    const pulseGeo = new THREE.SphereGeometry(radius * 0.8, 32, 32)
    const pulseMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(1.0, 0.2 * (1 - severity), 0.2 * (1 - severity)),
      transparent: true,
      opacity: 0.35 * intensity,
      side: THREE.DoubleSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    })
    const pulseSphere = new THREE.Mesh(pulseGeo, pulseMat)
    pulseSphere.userData.baseScale = 1.0
    pulseSphere.userData.mat = pulseMat
    pulseSphere.userData.type = 'pulse'
    zoneGroup.add(pulseSphere)
    this.riskMaterials.push(pulseMat)

    const ringGeo = new THREE.RingGeometry(radius * 0.3, radius, 64)
    const ringMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(1.0, 0.25 + 0.2 * (1 - severity), 0.1),
      transparent: true,
      opacity: 0.7 * intensity,
      side: THREE.DoubleSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    })
    const ring = new THREE.Mesh(ringGeo, ringMat)
    ring.lookAt(this.camera.position)
    ring.userData.mat = ringMat
    ring.userData.rotSpeed = 0.5 + Math.random() * 0.5
    ring.userData.type = 'ring'
    zoneGroup.add(ring)
    this.riskMaterials.push(ringMat)

    const haloGeo = new THREE.SphereGeometry(radius * 1.5, 32, 32)
    const haloMat = new THREE.MeshBasicMaterial({
      color: 0xff3333,
      transparent: true,
      opacity: 0.08 * intensity,
      side: THREE.BackSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    })
    const halo = new THREE.Mesh(haloGeo, haloMat)
    halo.userData.mat = haloMat
    halo.userData.type = 'halo'
    zoneGroup.add(halo)
    this.riskMaterials.push(haloMat)

    for (let ri = 0; ri < 3; ri++) {
      const shockGeo = new THREE.RingGeometry(
        radius * (0.4 + ri * 0.3),
        radius * (0.5 + ri * 0.3),
        64
      )
      const shockMat = new THREE.MeshBasicMaterial({
        color: 0xff5555,
        transparent: true,
        opacity: 0,
        side: THREE.DoubleSide,
        depthWrite: false,
        blending: THREE.AdditiveBlending
      })
      const shock = new THREE.Mesh(shockGeo, shockMat)
      shock.lookAt(this.camera.position)
      shock.userData = {
        ...shock.userData,
        mat: shockMat,
        delay: ri * 0.5,
        type: 'shock'
      }
      zoneGroup.add(shock)
      this.riskMaterials.push(shockMat)
    }

    zoneGroup.position.set(center.x, center.y, center.z)
    zoneGroup.userData = {
      zoneId,
      severity,
      isRiskZone: true,
      basePosition: { ...center }
    }

    this.scene.add(zoneGroup)
    this.riskZones.push(zoneGroup)

    return zoneGroup
  }

  /**
   * 添加爆发粒子效果
   */
  addEruption(options = {}) {
    const {
      center = { x: 0, y: 0, z: 0 },
      radius = 0.04,
      severity = 0.8,
      zoneId = `E${this.eruptionParticles.length + 1}`
    } = options

    const eruptionGroup = new THREE.Group()

    const particleSystem = new InstancedParticleSystem(this.scene, {
      particleSize: 0.015 + severity * 0.01,
      center,
      severity
    })
    particleSystem.emit({ center, radius, severity })

    const coreGeo = new THREE.SphereGeometry(radius * 0.5, 24, 24)
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xff4400,
      transparent: true,
      opacity: 0.7,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    })
    const core = new THREE.Mesh(coreGeo, coreMat)
    core.userData.mat = coreMat
    core.userData.type = 'core'
    eruptionGroup.add(core)

    const beamGeo = new THREE.CylinderGeometry(
      radius * 0.1, radius * 0.6, 0.5, 24, 1, true
    )
    const beamMat = new THREE.MeshBasicMaterial({
      color: 0xff6622,
      transparent: true,
      opacity: 0.25,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    })
    const beam = new THREE.Mesh(beamGeo, beamMat)
    beam.position.y = 0.25
    beam.userData.mat = beamMat
    beam.userData.type = 'beam'
    eruptionGroup.add(beam)

    const smokeGeo = new THREE.SphereGeometry(radius * 2.5, 16, 16)
    const smokeMat = new THREE.MeshBasicMaterial({
      color: 0x447744,
      transparent: true,
      opacity: 0.06,
      side: THREE.BackSide,
      depthWrite: false
    })
    const smoke = new THREE.Mesh(smokeGeo, smokeMat)
    smoke.position.y = radius * 0.5
    smoke.userData.mat = smokeMat
    smoke.userData.type = 'smoke'
    eruptionGroup.add(smoke)

    eruptionGroup.position.set(center.x, center.y, center.z)
    eruptionGroup.userData = {
      zoneId,
      severity,
      isEruption: true,
      basePosition: { ...center },
      particleSystem
    }

    this.scene.add(eruptionGroup)
    this.eruptionParticles.push(eruptionGroup)
    this.instancedParticleSystems.push(particleSystem)

    return eruptionGroup
  }

  /**
   * 每帧更新动画
   * @param {number} elapsed - Three.Clock.getElapsedTime()
   * @param {number} delta - 帧间增量
   */
  update(elapsed, delta = 0.016) {
    this.riskZones.forEach((zone, idx) => {
      const phase = elapsed * 2 + idx * 0.7
      zone.children.forEach(child => {
        const userData = child.userData || {}

        if (userData.type === 'pulse' && userData.mat) {
          const s = 1 + 0.25 * Math.sin(phase)
          child.scale.setScalar(s)
          userData.mat.opacity = userData.mat.opacity * 0.98 +
            (0.35 + 0.25 * (Math.sin(phase) * 0.5 + 0.5)) * 0.02
        }

        if (userData.type === 'ring' && userData.mat) {
          const s = 1 + 0.25 * Math.sin(phase)
          child.scale.setScalar(s)
          userData.mat.opacity = userData.mat.opacity * 0.98 +
            (0.35 + 0.25 * (Math.sin(phase) * 0.5 + 0.5)) * 0.02
          if (this.camera) child.lookAt(this.camera.position)
          if (userData.rotSpeed) {
            child.rotation.z += userData.rotSpeed * delta
          }
        }

        if (userData.type === 'halo' && userData.mat) {
          const s = 1 + 0.1 * Math.sin(phase * 0.5)
          child.scale.setScalar(s)
        }

        if (userData.type === 'shock') {
          const t = (elapsed + userData.delay) % 2.0 / 2.0
          child.scale.setScalar(1 + t * 3)
          userData.mat.opacity = (1 - t) * 0.5
          if (this.camera) child.lookAt(this.camera.position)
        }
      })
    })

    this.instancedParticleSystems.forEach(ps => ps.update())

    this.eruptionParticles.forEach(group => {
      group.children.forEach(child => {
        if (child.userData?.mat && !child.isPoints) {
          const m = child.userData.mat
          if (m.opacity !== undefined) {
            m.opacity = Math.max(0.1, m.opacity + Math.sin(elapsed * 5) * 0.02)
          }
        }
      })
    })
  }

  clearRiskZones() {
    this.riskZones.forEach(z => {
      this.scene.remove(z)
      z.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose()
        if (obj.material) {
          if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose())
          else obj.material.dispose()
        }
      })
    })
    this.riskZones = []
    this.riskMaterials = []
  }

  clearParticles() {
    this.instancedParticleSystems.forEach(ps => ps.dispose())
    this.instancedParticleSystems = []

    this.eruptionParticles.forEach(z => {
      this.scene.remove(z)
      z.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose()
        if (obj.material) {
          if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose())
          else obj.material.dispose()
        }
      })
    })
    this.eruptionParticles = []
  }

  clearAll() {
    this.clearRiskZones()
    this.clearParticles()
  }

  updateRiskZonesFromData(zones = []) {
    this.clearRiskZones()
    zones
      .filter(z => z.type === 'risk')
      .forEach(z => this.addRiskZone({
        center: z.center,
        radius: z.radius,
        severity: z.severity,
        zoneId: z.zone_id
      }))
  }

  updateEruptionsFromData(eruptions = []) {
    this.clearParticles()
    eruptions.forEach(z => this.addEruption({
      center: z.center,
      radius: z.radius,
      severity: z.severity,
      zoneId: z.patch_id || z.zone_id
    }))
  }

  getStats() {
    const instancedStats = this.instancedParticleSystems.map(ps => ps.getStats())
    return {
      riskZones: this.riskZones.length,
      eruptions: this.eruptionParticles.length,
      particles: instancedStats.reduce((s, st) => s + st.activeParticles, 0),
      maxParticles: instancedStats.reduce((s, st) => s + st.maxParticles, 0),
      drawCalls: instancedStats.reduce((s, st) => s + st.drawCalls, 0),
      isMobile: instancedStats.length > 0 ? instancedStats[0].isMobile : false
    }
  }

  dispose() {
    this.clearAll()
  }
}

export default RiskParticles
