import * as THREE from 'three'

/**
 * 锈蚀产物颜色映射
 */
const PRODUCT_COLORS = {
  malachite: 0x228B22,
  atacamite: 0x7CFC00,
  cassiterite: 0x8B4513,
  cuprite: 0xB22222,
  azurite: 0x1E90FF,
  unknown: 0x808080
}

const PRODUCT_NAMES = {
  malachite: '孔雀石',
  atacamite: '氯铜矿',
  cassiterite: '锡石',
  cuprite: '赤铜矿',
  azurite: '蓝铜矿',
  unknown: '未知'
}

/**
 * 脆弱性热力色阶（从蓝到红）
 */
const VULN_COLOR_STOPS = [
  { t: 0.0, color: new THREE.Color(0x3B82F6) },
  { t: 0.25, color: new THREE.Color(0x10B981) },
  { t: 0.5, color: new THREE.Color(0xF59E0B) },
  { t: 0.75, color: new THREE.Color(0xF97316) },
  { t: 1.0, color: new THREE.Color(0xEF4444) }
]

function getVulnerabilityColor(score) {
  const t = Math.max(0, Math.min(1, score / 100))
  for (let i = 0; i < VULN_COLOR_STOPS.length - 1; i++) {
    const a = VULN_COLOR_STOPS[i]
    const b = VULN_COLOR_STOPS[i + 1]
    if (t >= a.t && t <= b.t) {
      const k = (t - a.t) / (b.t - a.t)
      return a.color.clone().lerp(b.color, k)
    }
  }
  return VULN_COLOR_STOPS[VULN_COLOR_STOPS.length - 1].color
}

/* =======================================================================
   模块1：拉曼识别3D标注
   ======================================================================= */
export class RamanMarkers3D {
  constructor(scene, camera, options = {}) {
    this.scene = scene
    this.camera = camera
    this.options = {
      markerSize: 0.035,
      labelOffset: 0.05,
      ...options
    }
    this.markers = []
    this.root = new THREE.Group()
    this.root.name = 'RamanMarkers'
    this.scene.add(this.root)
    this._clock = new THREE.Clock()
  }

  addMarker(data) {
    const {
      artifact_id,
      position = { x: 0, y: 0, z: 0 },
      product_type = 'unknown',
      confidence = 0.5,
      product_color = null
    } = data

    const group = new THREE.Group()
    group.position.set(position.x, position.y, position.z)

    const color = product_color
      ? new THREE.Color(product_color)
      : new THREE.Color(PRODUCT_COLORS[product_type] || PRODUCT_COLORS.unknown)

    const coreGeo = new THREE.SphereGeometry(this.options.markerSize, 24, 24)
    const coreMat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.85,
      depthWrite: false
    })
    const core = new THREE.Mesh(coreGeo, coreMat)
    group.add(core)

    const ringGeo = new THREE.RingGeometry(
      this.options.markerSize * 1.4,
      this.options.markerSize * 2.0,
      48
    )
    const ringMat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.5,
      side: THREE.DoubleSide,
      depthWrite: false
    })
    const ring = new THREE.Mesh(ringGeo, ringMat)
    ring.lookAt(this.camera.position)
    group.add(ring)

    const haloGeo = new THREE.SphereGeometry(this.options.markerSize * 2.5, 24, 24)
    const haloMat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.12,
      depthWrite: false,
      side: THREE.BackSide
    })
    const halo = new THREE.Mesh(haloGeo, haloMat)
    group.add(halo)

    const marker = {
      id: `${artifact_id}_${Date.now()}_${this.markers.length}`,
      artifact_id,
      product_type,
      confidence,
      color,
      core,
      ring,
      halo,
      group,
      basePos: position
    }
    this.markers.push(marker)
    this.root.add(group)
    return marker
  }

  addMarkersFromList(list) {
    list.forEach(d => this.addMarker(d))
  }

  clear() {
    this.markers.forEach(m => {
      this.root.remove(m.group)
      m.core.geometry?.dispose()
      m.core.material?.dispose()
      m.ring.geometry?.dispose()
      m.ring.material?.dispose()
      m.halo.geometry?.dispose()
      m.halo.material?.dispose()
    })
    this.markers = []
  }

  update(elapsed) {
    const t = elapsed
    this.markers.forEach(m => {
      m.ring.lookAt(this.camera.position)
      m.core.position.y = Math.sin(t * 1.8) * 0.004
      const pulse = 0.85 + Math.sin(t * 2.5 + m.basePos.x * 10) * 0.15
      m.ring.material.opacity = 0.35 + 0.25 * Math.sin(t * 2.0)
      m.ring.scale.setScalar(pulse)
      m.halo.scale.setScalar(1.0 + 0.15 * Math.sin(t * 1.2))
      m.core.material.opacity = 0.75 + 0.2 * Math.sin(t * 3.0)
    })
  }

  getLegend() {
    return Object.entries(PRODUCT_NAMES).map(([k, v]) => ({
      key: k,
      name: v,
      color: '#' + PRODUCT_COLORS[k].toString(16).padStart(6, '0')
    }))
  }
}

/* =======================================================================
   模块2：喷涂轨迹可视化
   ======================================================================= */
export class SprayPathTrajectory {
  constructor(scene, camera, options = {}) {
    this.scene = scene
    this.camera = camera
    this.options = {
      pathWidth: 1.2,
      showSprayCones: true,
      sprayColor: 0x60A5FA,
      pathColor: 0x34D399,
      ...options
    }
    this.root = new THREE.Group()
    this.root.name = 'SprayTrajectory'
    this.scene.add(this.root)
    this.waypoints = []
    this.pathLine = null
    this.cones = []
    this.currentPointIndex = 0
    this.progress = 0
    this.playing = false
    this._clock = new THREE.Clock()
    this.robotEnd = null
  }

  clear() {
    this.waypoints = []
    this.cones.forEach(c => {
      this.root.remove(c)
      c.geometry?.dispose()
      c.material?.dispose()
    })
    this.cones = []
    if (this.pathLine) {
      this.root.remove(this.pathLine)
      this.pathLine.geometry?.dispose()
      this.pathLine.material?.dispose()
      this.pathLine = null
    }
    if (this.robotEnd) {
      this.root.remove(this.robotEnd)
      this.robotEnd.geometry?.dispose()
      this.robotEnd.material?.dispose()
      this.robotEnd = null
    }
    this.currentPointIndex = 0
    this.progress = 0
    this.playing = false
  }

  loadPlan(plan) {
    this.clear()
    if (!plan || !plan.waypoints || plan.waypoints.length === 0) return

    this.waypoints = plan.waypoints
    const points = this.waypoints.map(
      wp => new THREE.Vector3(wp.x, wp.y, wp.z)
    )

    const curve = new THREE.CatmullRomCurve3(points, false, 'catmullrom', 0.5)
    const curvePoints = curve.getPoints(Math.max(100, points.length * 20))

    const geo = new THREE.BufferGeometry().setFromPoints(curvePoints)
    const mat = new THREE.LineBasicMaterial({
      color: this.options.pathColor,
      transparent: true,
      opacity: 0.75,
      linewidth: this.options.pathWidth
    })
    this.pathLine = new THREE.Line(geo, mat)
    this.root.add(this.pathLine)

    if (this.options.showSprayCones) {
      this.waypoints.forEach((wp, i) => {
        const intensity = 0.5 + 0.5 * (wp.dwell_time_s / Math.max(...this.waypoints.map(w => w.dwell_time_s || 1)))
        const coneGeo = new THREE.ConeGeometry(
          0.015 + 0.015 * intensity,
          0.06 + 0.04 * intensity,
          24
        )
        const coneMat = new THREE.MeshBasicMaterial({
          color: this.options.sprayColor,
          transparent: true,
          opacity: 0.55 * intensity,
          depthWrite: false
        })
        const cone = new THREE.Mesh(coneGeo, coneMat)
        cone.position.set(wp.x, wp.y, wp.z)

        const dir = new THREE.Vector3(
          wp.orientation?.[0] || 0,
          wp.orientation?.[1] || 0,
          wp.orientation?.[2] || -1
        ).normalize()
        const target = new THREE.Vector3(wp.x, wp.y, wp.z).add(dir)
        cone.lookAt(target)
        cone.rotateX(Math.PI / 2)
        cone.userData = {
          index: i,
          dwell: wp.dwell_time_s,
          flow: wp.flow_rate_ml_s,
          baseIntensity: intensity
        }
        this.cones.push(cone)
        this.root.add(cone)
      })
    }

    const endGeo = new THREE.SphereGeometry(0.012, 16, 16)
    const endMat = new THREE.MeshBasicMaterial({ color: 0xFBBF24, depthWrite: false })
    this.robotEnd = new THREE.Mesh(endGeo, endMat)
    if (this.waypoints.length) {
      const w = this.waypoints[0]
      this.robotEnd.position.set(w.x, w.y, w.z)
    }
    this.root.add(this.robotEnd)
  }

  play(speed = 1.0) {
    this.playing = true
    this._playSpeed = speed
  }

  pause() {
    this.playing = false
  }

  reset() {
    this.currentPointIndex = 0
    this.progress = 0
    if (this.waypoints.length && this.robotEnd) {
      const w = this.waypoints[0]
      this.robotEnd.position.set(w.x, w.y, w.z)
    }
  }

  update(elapsed, dt) {
    this.cones.forEach(c => {
      const i = c.userData.baseIntensity
      c.material.opacity = 0.35 + 0.3 * i * (0.85 + 0.15 * Math.sin(elapsed * 4.0 + c.userData.index))
      c.scale.y = 1.0 + 0.08 * Math.sin(elapsed * 3.0 + c.userData.index)
    })

    if (this.playing && this.waypoints.length > 1 && this.robotEnd) {
      const total = this.waypoints.length - 1
      this.progress += (dt * 0.25 * (this._playSpeed || 1)) / Math.max(total, 1)
      if (this.progress > 1) {
        this.progress = 0
      }
      const absPos = this.progress * total
      const i = Math.floor(absPos)
      const k = absPos - i
      const a = this.waypoints[Math.min(i, total)]
      const b = this.waypoints[Math.min(i + 1, total)]
      this.robotEnd.position.set(
        a.x + (b.x - a.x) * k,
        a.y + (b.y - a.y) * k,
        a.z + (b.z - a.z) * k
      )
      this.robotEnd.scale.setScalar(1.0 + 0.3 * Math.sin(elapsed * 8))
    }
  }

  getStats() {
    if (!this.waypoints.length) return null
    const distances = []
    for (let i = 0; i < this.waypoints.length - 1; i++) {
      const a = this.waypoints[i]
      const b = this.waypoints[i + 1]
      distances.push(Math.hypot(b.x - a.x, b.y - a.y, b.z - a.z))
    }
    return {
      waypointCount: this.waypoints.length,
      totalDistance: distances.reduce((s, d) => s + d, 0),
      totalTime: this.waypoints.reduce((s, w) => s + (w.dwell_time_s || 0), 0),
      totalVolume: this.waypoints.reduce((s, w) => s + (w.flow_rate_ml_s || 0) * (w.dwell_time_s || 0), 0)
    }
  }
}

/* =======================================================================
   模块3：脆弱性热力层（展厅平面）
   ======================================================================= */
export class VulnerabilityHeatmap {
  constructor(scene, camera, options = {}) {
    this.scene = scene
    this.camera = camera
    this.options = {
      hallWidth: 12,
      hallDepth: 10,
      cellSize: 0.5,
      sigma: 0.8,
      baseY: -0.05,
      ...options
    }
    this.root = new THREE.Group()
    this.root.name = 'VulnerabilityHeatmap'
    this.scene.add(this.root)
    this.dataPoints = []
    this.heatMesh = null
    this.dots = []
    this._built = false
  }

  clear() {
    this.dataPoints = []
    this.dots.forEach(d => {
      this.root.remove(d)
      d.geometry?.dispose()
      d.material?.dispose()
    })
    this.dots = []
    if (this.heatMesh) {
      this.root.remove(this.heatMesh)
      this.heatMesh.geometry?.dispose()
      this.heatMesh.material?.dispose()
      this.heatMesh = null
    }
    this._built = false
  }

  loadData(points) {
    this.clear()
    this.dataPoints = points || []
    this._buildHeatmap()
    this._buildDots()
  }

  _buildHeatmap() {
    const { hallWidth, hallDepth, cellSize, sigma } = this.options
    const cols = Math.ceil(hallWidth / cellSize)
    const rows = Math.ceil(hallDepth / cellSize)
    const halfW = hallWidth / 2
    const halfD = hallDepth / 2

    const values = new Float32Array(cols * rows)
    const weights = new Float32Array(cols * rows)
    const twosig2 = 2 * sigma * sigma

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const cx = (c + 0.5) * cellSize - halfW
        const cz = (r + 0.5) * cellSize - halfD
        let num = 0
        let den = 0
        this.dataPoints.forEach(p => {
          const px = (p.x || 0) - halfW
          const pz = (p.y || 0) - halfD
          const dx = cx - px
          const dz = cz - pz
          const d2 = dx * dx + dz * dz
          const w = Math.exp(-d2 / twosig2)
          num += (p.value || 0) * w
          den += w
        })
        const idx = r * cols + c
        values[idx] = den > 0.01 ? num / den : 0
        weights[idx] = den
      }
    }

    const geo = new THREE.PlaneGeometry(hallWidth, hallDepth, cols, rows)
    geo.rotateX(-Math.PI / 2)
    const colors = []
    const posAttr = geo.attributes.position
    for (let i = 0; i < posAttr.count; i++) {
      const x = posAttr.getX(i)
      const z = posAttr.getZ(i)
      const c = Math.floor((x + halfW) / cellSize)
      const r = Math.floor((z + halfD) / cellSize)
      const ci = Math.max(0, Math.min(cols - 1, c))
      const ri = Math.max(0, Math.min(rows - 1, r))
      const v = values[ri * cols + ci]
      const col = getVulnerabilityColor(v)
      colors.push(col.r, col.g, col.b)
    }
    geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))

    const mat = new THREE.MeshBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.55,
      side: THREE.DoubleSide,
      depthWrite: false
    })
    this.heatMesh = new THREE.Mesh(geo, mat)
    this.heatMesh.position.y = this.options.baseY
    this.root.add(this.heatMesh)
    this._built = true
  }

  _buildDots() {
    this.dataPoints.forEach(p => {
      const halfW = this.options.hallWidth / 2
      const halfD = this.options.hallDepth / 2
      const geo = new THREE.SphereGeometry(0.04, 16, 16)
      const col = getVulnerabilityColor(p.value || 0)
      const mat = new THREE.MeshBasicMaterial({
        color: col,
        transparent: true,
        opacity: 0.9,
        depthWrite: false
      })
      const dot = new THREE.Mesh(geo, mat)
      dot.position.set((p.x || 0) - halfW, this.options.baseY + 0.015, (p.y || 0) - halfD)
      dot.userData = p
      this.dots.push(dot)
      this.root.add(dot)
    })
  }

  update(elapsed) {
    this.dots.forEach((d, i) => {
      d.position.y = this.options.baseY + 0.015 + 0.006 * Math.sin(elapsed * 2.5 + i)
      d.scale.setScalar(1.0 + 0.15 * Math.sin(elapsed * 3.0 + i * 0.5))
    })
  }

  getLegend() {
    return [
      { label: '0-20 优秀', value: 10, color: '#3B82F6' },
      { label: '20-40 良好', value: 30, color: '#10B981' },
      { label: '40-60 中等', value: 50, color: '#F59E0B' },
      { label: '60-80 高度', value: 70, color: '#F97316' },
      { label: '80-100 极度', value: 90, color: '#EF4444' }
    ]
  }
}

/* =======================================================================
   模块4：缓蚀剂寿命倒计时3D徽标
   ======================================================================= */
export class LifetimeBadges3D {
  constructor(scene, camera, options = {}) {
    this.scene = scene
    this.camera = camera
    this.options = {
      size: 0.045,
      ...options
    }
    this.root = new THREE.Group()
    this.root.name = 'LifetimeBadges'
    this.scene.add(this.root)
    this.badges = []
    this._clock = new THREE.Clock()
  }

  clear() {
    this.badges.forEach(b => {
      this.root.remove(b.group)
      b.ring.geometry?.dispose()
      b.ring.material?.dispose()
      b.disc.geometry?.dispose()
      b.disc.material?.dispose()
    })
    this.badges = []
  }

  addBadge(data) {
    const {
      artifact_id,
      position = { x: 0, y: 0, z: 0 },
      remaining_days = 180,
      status = 'good',
      status_color = '#3B82F6',
      need_respray = false
    } = data

    const group = new THREE.Group()
    group.position.set(position.x, position.y, position.z)

    const s = this.options.size
    const ringGeo = new THREE.RingGeometry(s * 0.85, s, 64)
    const ringMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(status_color),
      transparent: true,
      opacity: 0.85,
      side: THREE.DoubleSide,
      depthWrite: false
    })
    const ring = new THREE.Mesh(ringGeo, ringMat)
    ring.lookAt(this.camera.position)
    group.add(ring)

    const ratio = Math.max(0, Math.min(1, remaining_days / 365))
    const discGeo = new THREE.RingGeometry(s * 0.2, s * 0.75, 64, 1, -Math.PI / 2, ratio * Math.PI * 2)
    const discMat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(status_color),
      transparent: true,
      opacity: need_respray ? 0.95 : 0.6,
      side: THREE.DoubleSide,
      depthWrite: false
    })
    const disc = new THREE.Mesh(discGeo, discMat)
    disc.lookAt(this.camera.position)
    group.add(disc)

    const badge = {
      id: artifact_id,
      remaining_days,
      status,
      need_respray,
      group,
      ring,
      disc
    }
    this.badges.push(badge)
    this.root.add(group)
    return badge
  }

  loadBadges(list) {
    this.clear()
    list.forEach(b => this.addBadge(b))
  }

  update(elapsed) {
    this.badges.forEach((b, i) => {
      b.ring.lookAt(this.camera.position)
      b.disc.lookAt(this.camera.position)
      if (b.need_respray) {
        const flash = 0.55 + 0.45 * Math.abs(Math.sin(elapsed * 3.5 + i))
        b.ring.material.opacity = flash
        b.disc.material.opacity = 0.7 + 0.3 * Math.abs(Math.sin(elapsed * 3.5 + i))
      } else {
        b.ring.material.opacity = 0.7 + 0.15 * Math.sin(elapsed * 1.2 + i)
      }
    })
  }
}
