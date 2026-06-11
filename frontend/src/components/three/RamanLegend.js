import * as THREE from 'three'
import { PRODUCT_COLORS, PRODUCT_NAMES } from './constants.js'

/**
 * 拉曼光谱识别3D标注 + 图例组件
 * 按锈蚀产物类型用不同颜色标注，包含脉冲动画，始终面向相机
 */
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

/**
 * 拉曼光谱图例组件（DOM/Canvas 2D 风格，可供UI层使用）
 */
export class RamanLegend {
  constructor(container, options = {}) {
    this.container = container
    this.options = {
      title: '锈蚀产物类型',
      ...options
    }
    this.items = []
    this._build()
  }

  _build() {
    this.el = document.createElement('div')
    this.el.className = 'raman-legend'
    this.el.style.cssText = `
      position: absolute;
      right: 16px;
      bottom: 16px;
      background: rgba(17, 24, 39, 0.85);
      color: #fff;
      padding: 12px 16px;
      border-radius: 8px;
      font-size: 12px;
      backdrop-filter: blur(4px);
      min-width: 140px;
      z-index: 10;
    `
    const title = document.createElement('div')
    title.style.cssText = 'font-weight: 600; margin-bottom: 8px; font-size: 13px;'
    title.textContent = this.options.title
    this.el.appendChild(title)

    this.listEl = document.createElement('div')
    this.listEl.style.cssText = 'display: flex; flex-direction: column; gap: 6px;'
    this.el.appendChild(this.listEl)

    this._renderLegend()
    this.container.appendChild(this.el)
  }

  _renderLegend() {
    this.listEl.innerHTML = ''
    Object.entries(PRODUCT_NAMES).forEach(([key, name]) => {
      const item = document.createElement('div')
      item.style.cssText = 'display: flex; align-items: center; gap: 8px;'
      const dot = document.createElement('span')
      dot.style.cssText = `
        width: 10px; height: 10px; border-radius: 50%;
        background: #${PRODUCT_COLORS[key].toString(16).padStart(6, '0')};
        flex-shrink: 0;
      `
      const label = document.createElement('span')
      label.textContent = name
      item.appendChild(dot)
      item.appendChild(label)
      this.listEl.appendChild(item)
    })
  }

  setActive(productType) {
    const items = this.listEl.querySelectorAll('div')
    items.forEach((item, i) => {
      const key = Object.keys(PRODUCT_NAMES)[i]
      item.style.opacity = productType && key === productType ? '1' : '0.6'
    })
  }

  destroy() {
    if (this.el && this.el.parentNode) {
      this.el.parentNode.removeChild(this.el)
    }
    this.el = null
  }
}
