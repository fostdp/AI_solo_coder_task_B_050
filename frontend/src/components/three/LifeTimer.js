import * as THREE from 'three'
import { LIFE_STATUS_COLORS, LIFE_STATUS_NAMES } from './constants.js'

/**
 * 缓蚀剂寿命倒计时 3D 徽标组件
 * 环形进度条 + 颜色状态指示，需重喷涂时闪烁提醒
 */
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
      status_color = null,
      need_respray = false
    } = data

    const group = new THREE.Group()
    group.position.set(position.x, position.y, position.z)

    const color = new THREE.Color(
      status_color || LIFE_STATUS_COLORS[status] || LIFE_STATUS_COLORS.good
    )

    const s = this.options.size
    const ringGeo = new THREE.RingGeometry(s * 0.85, s, 64)
    const ringMat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.85,
      side: THREE.DoubleSide,
      depthWrite: false
    })
    const ring = new THREE.Mesh(ringGeo, ringMat)
    ring.lookAt(this.camera.position)
    group.add(ring)

    const ratio = Math.max(0, Math.min(1, remaining_days / 365))
    const discGeo = new THREE.RingGeometry(
      s * 0.2, s * 0.75, 64, 1,
      -Math.PI / 2, ratio * Math.PI * 2
    )
    const discMat = new THREE.MeshBasicMaterial({
      color,
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

/**
 * 寿命倒计时 UI 组件（数字显示）
 */
export class LifeTimer {
  constructor(container, options = {}) {
    this.container = container
    this.options = {
      title: '缓蚀剂剩余寿命',
      ...options
    }
    this.remainingSeconds = 0
    this._timer = null
    this._build()
  }

  _build() {
    this.el = document.createElement('div')
    this.el.className = 'life-timer'
    this.el.style.cssText = `
      background: rgba(17, 24, 39, 0.85);
      color: #fff;
      padding: 14px 18px;
      border-radius: 10px;
      backdrop-filter: blur(4px);
      min-width: 200px;
    `

    const title = document.createElement('div')
    title.style.cssText = 'font-size: 12px; color: #9CA3AF; margin-bottom: 6px;'
    title.textContent = this.options.title
    this.el.appendChild(title)

    this.daysEl = document.createElement('div')
    this.daysEl.style.cssText = 'font-size: 28px; font-weight: 700; line-height: 1;'
    this.daysEl.textContent = '-- 天'
    this.el.appendChild(this.daysEl)

    this.timeEl = document.createElement('div')
    this.timeEl.style.cssText = 'font-size: 13px; color: #6B7280; margin-top: 4px;'
    this.timeEl.textContent = '--:--:--'
    this.el.appendChild(this.timeEl)

    this.statusEl = document.createElement('div')
    this.statusEl.style.cssText = `
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 11px;
      margin-top: 8px;
    `
    this.el.appendChild(this.statusEl)

    this.container.appendChild(this.el)
  }

  setData(remainingDays, status = 'good') {
    this.remainingSeconds = Math.max(0, remainingDays * 86400)
    this._updateDisplay()
    this._updateStatus(status)
  }

  start() {
    this.stop()
    this._timer = setInterval(() => {
      this.remainingSeconds = Math.max(0, this.remainingSeconds - 1)
      this._updateDisplay()
    }, 1000)
  }

  stop() {
    if (this._timer) {
      clearInterval(this._timer)
      this._timer = null
    }
  }

  _updateDisplay() {
    const total = this.remainingSeconds
    const days = Math.floor(total / 86400)
    const hours = Math.floor((total % 86400) / 3600)
    const mins = Math.floor((total % 3600) / 60)
    const secs = Math.floor(total % 60)
    this.daysEl.textContent = `${days} 天`
    this.timeEl.textContent = [
      String(hours).padStart(2, '0'),
      String(mins).padStart(2, '0'),
      String(secs).padStart(2, '0')
    ].join(':')
  }

  _updateStatus(status) {
    const color = LIFE_STATUS_COLORS[status] || '#6B7280'
    const name = LIFE_STATUS_NAMES[status] || status
    this.statusEl.style.background = color + '33'
    this.statusEl.style.color = color
    this.statusEl.textContent = name
  }

  destroy() {
    this.stop()
    if (this.el && this.el.parentNode) {
      this.el.parentNode.removeChild(this.el)
    }
    this.el = null
  }
}
