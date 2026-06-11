import * as THREE from 'three'

/**
 * 青铜器 3D 模型模块
 * 负责 5 类青铜器型的程序化建模与材质
 * 用法:
 *   const model = new BronzeModel()
 *   model.build('simsimuwu')
 *   scene.add(model.group)
 */
export class BronzeModel {
  constructor(options = {}) {
    this.group = new THREE.Group()
    this.patinaLevel = options.patinaLevel ?? 0.3
    this.showWireframe = options.showWireframe ?? false
    this.currentStyle = null
    this._materials = []
  }

  build(style = 'simsimuwu') {
    this.clear()
    this.currentStyle = style

    switch (style) {
      case 'simsimuwu': this._createSimMuWuDing(); break
      case 'siyangfangzun': this._createSiYangFangZun(); break
      case 'jue': this._createJue(); break
      case 'zhong': this._createBell(); break
      case 'jian': this._createSword(); break
      default: this._createSimMuWuDing()
    }

    if (this.showWireframe) {
      this.group.traverse(obj => {
        if (obj.isMesh) {
          const wf = new THREE.WireframeGeometry(obj.geometry)
          const wfMat = new THREE.LineBasicMaterial({
            color: 0xffaa55,
            transparent: true,
            opacity: 0.3
          })
          obj.add(new THREE.LineSegments(wf, wfMat))
        }
      })
    }

    return this.group
  }

  clear() {
    while (this.group.children.length > 0) {
      const child = this.group.children[0]
      this.group.remove(child)
      if (child.geometry) child.geometry.dispose()
      if (child.material) {
        if (Array.isArray(child.material)) {
          child.material.forEach(m => m.dispose())
        } else {
          child.material.dispose()
        }
      }
    }
    this._materials = []
    this.currentStyle = null
  }

  _createBronzeMaterial(patinaLevel = 0.3) {
    const mat = new THREE.MeshStandardMaterial({
      color: new THREE.Color().setHSL(0.08, 0.4, 0.35 * (1 - patinaLevel * 0.3)),
      metalness: 0.9,
      roughness: 0.55 - patinaLevel * 0.2,
      envMapIntensity: 1.0
    })
    this._materials.push(mat)
    return mat
  }

  _createGreenPatinaMaterial() {
    const mat = new THREE.MeshStandardMaterial({
      color: 0x3c7a4d,
      metalness: 0.6,
      roughness: 0.85
    })
    this._materials.push(mat)
    return mat
  }

  _createSimMuWuDing() {
    const bronze = this._createBronzeMaterial(0.4)
    const patina = this._createGreenPatinaMaterial()
    const bodyGroup = new THREE.Group()

    const bodyGeo = new THREE.BoxGeometry(0.7, 0.45, 0.5)
    const body = new THREE.Mesh(bodyGeo, bronze)
    body.position.y = 0.05
    body.castShadow = true
    body.receiveShadow = true
    bodyGroup.add(body)

    const rimGeo = new THREE.BoxGeometry(0.78, 0.06, 0.58)
    const rim = new THREE.Mesh(rimGeo, bronze)
    rim.position.y = 0.30
    rim.castShadow = true
    bodyGroup.add(rim)

    for (let i = 0; i < 4; i++) {
      const earGeo = new THREE.TorusGeometry(0.08, 0.025, 16, 32, Math.PI)
      const ear = new THREE.Mesh(earGeo, bronze)
      ear.rotation.z = Math.PI
      ear.position.set(
        i < 2 ? -0.22 : 0.22,
        0.36,
        i % 2 === 0 ? -0.18 : 0.18
      )
      ear.rotation.x = i % 2 === 0 ? 0 : Math.PI
      ear.castShadow = true
      bodyGroup.add(ear)
    }

    const legPositions = [
      [-0.25, -0.2, -0.16], [0.25, -0.2, -0.16],
      [-0.25, -0.2, 0.16], [0.25, -0.2, 0.16]
    ]
    legPositions.forEach(([x, y, z]) => {
      const legGeo = new THREE.CylinderGeometry(0.045, 0.055, 0.28, 16)
      const leg = new THREE.Mesh(legGeo, bronze)
      leg.position.set(x, y, z)
      leg.castShadow = true
      bodyGroup.add(leg)

      const footGeo = new THREE.CylinderGeometry(0.065, 0.07, 0.04, 16)
      const foot = new THREE.Mesh(footGeo, bronze)
      foot.position.set(x, y - 0.15, z)
      foot.castShadow = true
      bodyGroup.add(foot)
    })

    for (let fi = 0; fi < 50; fi++) {
      const patchGeo = new THREE.CircleGeometry(0.015 + Math.random() * 0.03, 12)
      const patch = new THREE.Mesh(patchGeo, patina)
      const side = Math.floor(Math.random() * 4)
      let px = 0, py = 0, pz = 0, ry = 0
      if (side === 0) { px = (Math.random() - 0.5) * 0.6; py = Math.random() * 0.4; pz = 0.251; ry = 0 }
      else if (side === 1) { px = (Math.random() - 0.5) * 0.6; py = Math.random() * 0.4; pz = -0.251; ry = Math.PI }
      else if (side === 2) { px = 0.351; py = Math.random() * 0.4; pz = (Math.random() - 0.5) * 0.4; ry = Math.PI / 2 }
      else { px = -0.351; py = Math.random() * 0.4; pz = (Math.random() - 0.5) * 0.4; ry = -Math.PI / 2 }
      patch.position.set(px, py - 0.15, pz)
      patch.rotation.y = ry + (Math.random() - 0.5) * 0.5
      bodyGroup.add(patch)
    }

    bodyGroup.position.y = 0.1
    this.group.add(bodyGroup)
  }

  _createSiYangFangZun() {
    const bronze = this._createBronzeMaterial(0.35)
    const patina = this._createGreenPatinaMaterial()
    const group = new THREE.Group()

    const bodyGeo = new THREE.BoxGeometry(0.4, 0.5, 0.4)
    const body = new THREE.Mesh(bodyGeo, bronze)
    body.position.y = 0.1
    body.castShadow = true
    group.add(body)

    const neckGeo = new THREE.CylinderGeometry(0.12, 0.18, 0.2, 32)
    const neck = new THREE.Mesh(neckGeo, bronze)
    neck.position.y = 0.45
    neck.castShadow = true
    group.add(neck)

    const mouthGeo = new THREE.CylinderGeometry(0.18, 0.12, 0.06, 32)
    const mouth = new THREE.Mesh(mouthGeo, bronze)
    mouth.position.y = 0.58
    mouth.castShadow = true
    group.add(mouth)

    const baseGeo = new THREE.CylinderGeometry(0.22, 0.2, 0.12, 32)
    const base = new THREE.Mesh(baseGeo, bronze)
    base.position.y = -0.22
    base.castShadow = true
    group.add(base)

    const positions = [
      { x: 0, y: 0.15, z: 0.22, ry: 0 },
      { x: 0, y: 0.15, z: -0.22, ry: Math.PI },
      { x: 0.22, y: 0.15, z: 0, ry: Math.PI / 2 },
      { x: -0.22, y: 0.15, z: 0, ry: -Math.PI / 2 }
    ]
    positions.forEach(p => {
      const headGroup = new THREE.Group()
      const hornGeo = new THREE.ConeGeometry(0.03, 0.12, 8)
      const hornL = new THREE.Mesh(hornGeo, bronze)
      hornL.position.set(-0.06, 0.12, 0)
      hornL.rotation.z = 0.4
      headGroup.add(hornL)
      const hornR = new THREE.Mesh(hornGeo, bronze)
      hornR.position.set(0.06, 0.12, 0)
      hornR.rotation.z = -0.4
      headGroup.add(hornR)
      const headGeo = new THREE.SphereGeometry(0.07, 16, 16)
      const head = new THREE.Mesh(headGeo, bronze)
      head.scale.set(1.2, 0.8, 1)
      headGroup.add(head)
      headGroup.position.set(p.x, p.y, p.z)
      headGroup.rotation.y = p.ry
      headGroup.rotation.x = 0.3
      group.add(headGroup)
    })

    group.position.y = 0.1
    this.group.add(group)
  }

  _createJue() {
    const bronze = this._createBronzeMaterial(0.25)
    const group = new THREE.Group()

    const cupGeo = new THREE.CylinderGeometry(0.08, 0.05, 0.18, 32)
    const cup = new THREE.Mesh(cupGeo, bronze)
    cup.position.y = 0.15
    cup.castShadow = true
    group.add(cup)

    const streamGeo = new THREE.CylinderGeometry(0.015, 0.025, 0.2, 12)
    const stream = new THREE.Mesh(streamGeo, bronze)
    stream.position.set(0.12, 0.22, 0)
    stream.rotation.z = -Math.PI / 2.5
    stream.castShadow = true
    group.add(stream)

    const tailGeo = new THREE.CylinderGeometry(0.015, 0.02, 0.15, 12)
    const tail = new THREE.Mesh(tailGeo, bronze)
    tail.position.set(-0.09, 0.22, 0)
    tail.rotation.z = Math.PI / 2.5
    tail.castShadow = true
    group.add(tail)

    for (let i = 0; i < 3; i++) {
      const legGeo = new THREE.CylinderGeometry(0.012, 0.018, 0.22, 12)
      const leg = new THREE.Mesh(legGeo, bronze)
      const angle = (i / 3) * Math.PI * 2
      leg.position.set(Math.cos(angle) * 0.04, 0.04, Math.sin(angle) * 0.04)
      leg.castShadow = true
      group.add(leg)
    }

    const pillarGeo = new THREE.CylinderGeometry(0.01, 0.01, 0.08, 8)
    const pillar = new THREE.Mesh(pillarGeo, bronze)
    pillar.position.set(0, 0.28, 0)
    group.add(pillar)

    group.position.y = 0.05
    this.group.add(group)
  }

  _createBell() {
    const bronze = this._createBronzeMaterial(0.35)
    const group = new THREE.Group()

    for (let i = 0; i < 7; i++) {
      const scale = 1 - i * 0.08
      const bellGeo = new THREE.CylinderGeometry(
        0.08 * scale, 0.12 * scale, 0.2 * scale, 24
      )
      const bell = new THREE.Mesh(bellGeo, bronze)
      bell.position.set(i * 0.18 - 0.54, 0.15 + i * 0.02, 0)
      bell.castShadow = true
      group.add(bell)

      const knobGeo = new THREE.SphereGeometry(0.015 * scale, 12, 12)
      const positions = [[-1, -1], [1, -1], [-1, 1], [1, 1]]
      positions.forEach(([dx, dy]) => {
        const knob = new THREE.Mesh(knobGeo, bronze)
        knob.position.set(
          i * 0.18 - 0.54 + dx * 0.08 * scale,
          0.05 + i * 0.02,
          dy * 0.1 * scale
        )
        group.add(knob)
      })
    }

    const beamGeo = new THREE.BoxGeometry(1.5, 0.05, 0.08)
    const beam = new THREE.Mesh(beamGeo, bronze)
    beam.position.y = 0.4
    group.add(beam)

    const postGeo = new THREE.CylinderGeometry(0.03, 0.035, 0.5, 16)
    const postL = new THREE.Mesh(postGeo, bronze)
    postL.position.set(-0.75, 0.15, 0)
    group.add(postL)
    const postR = new THREE.Mesh(postGeo, bronze)
    postR.position.set(0.75, 0.15, 0)
    group.add(postR)

    this.group.add(group)
  }

  _createSword() {
    const bronze = this._createBronzeMaterial(0.3)
    const group = new THREE.Group()

    const bladeGeo = new THREE.BoxGeometry(0.04, 0.02, 0.9)
    const blade = new THREE.Mesh(bladeGeo, bronze)
    blade.position.z = 0.25
    blade.castShadow = true
    group.add(blade)

    const tipGeo = new THREE.ConeGeometry(0.025, 0.12, 4)
    const tip = new THREE.Mesh(tipGeo, bronze)
    tip.rotation.x = -Math.PI / 2
    tip.position.z = 0.76
    tip.castShadow = true
    group.add(tip)

    const guardGeo = new THREE.BoxGeometry(0.2, 0.02, 0.04)
    const guard = new THREE.Mesh(guardGeo, bronze)
    guard.position.z = -0.22
    guard.castShadow = true
    group.add(guard)

    const handleGeo = new THREE.CylinderGeometry(0.018, 0.018, 0.2, 16)
    const handle = new THREE.Mesh(handleGeo, bronze)
    handle.rotation.x = Math.PI / 2
    handle.position.z = -0.34
    group.add(handle)

    const pommelGeo = new THREE.SphereGeometry(0.03, 16, 16)
    const pommel = new THREE.Mesh(pommelGeo, bronze)
    pommel.position.z = -0.45
    group.add(pommel)

    group.rotation.y = Math.PI / 2
    group.position.y = 0.1
    this.group.add(group)
  }

  getMaterials() {
    return this._materials
  }

  dispose() {
    this.clear()
    this._materials = []
  }
}

export default BronzeModel
