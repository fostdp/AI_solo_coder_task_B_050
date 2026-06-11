import * as THREE from 'three'

/**
 * 喷涂路径轨迹可视化组件
 * CatmullRom曲线平滑路径 + 喷嘴锥 + 机械臂末端运动动画
 * 支持播放/暂停/重置控制
 */
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
    this._playSpeed = 1.0
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
      const maxDwell = Math.max(...this.waypoints.map(w => w.dwell_time_s || 1))
      this.waypoints.forEach((wp, i) => {
        const intensity = 0.5 + 0.5 * (wp.dwell_time_s / maxDwell)
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
      totalVolume: this.waypoints.reduce(
        (s, w) => s + (w.flow_rate_ml_s || 0) * (w.dwell_time_s || 0), 0
      )
    }
  }
}

/**
 * 喷涂路径动画控制器（简化API）
 */
export class SprayPath {
  constructor(scene, camera, options = {}) {
    this._trajectory = new SprayPathTrajectory(scene, camera, options)
    this.scene = scene
  }

  get root() { return this._trajectory.root }
  get playing() { return this._trajectory.playing }

  load(plan) { this._trajectory.loadPlan(plan) }
  play(speed) { this._trajectory.play(speed) }
  pause() { this._trajectory.pause() }
  reset() { this._trajectory.reset() }
  update(elapsed, dt) { this._trajectory.update(elapsed, dt) }
  clear() { this._trajectory.clear() }
  getStats() { return this._trajectory.getStats() }
}
