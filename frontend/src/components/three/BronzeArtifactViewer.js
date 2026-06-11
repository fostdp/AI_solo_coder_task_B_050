import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import TWEEN from '@tweenjs/tween.js'
import { BronzeModel } from './BronzeModel.js'
import { RiskParticles } from './RiskParticles.js'

/**
 * 青铜器 3D 查看器 (v3.0 模块化重构版)
 *
 * 模块拆分:
 *   - BronzeModel:   青铜器 5 类器型程序化建模
 *   - RiskParticles: 风险区脉冲光效 + 爆发粒子系统
 *   - BronzeArtifactViewer: 场景、相机、光照、动画循环 (本文件)
 *
 * 向后兼容: 所有 v2.0 的 public API 保持不变
 */
export class BronzeArtifactViewer {
  constructor(container, options = {}) {
    this.container = container
    this.options = {
      backgroundColor: 0x0a0e1a,
      antialias: true,
      autoRotate: false,
      showWireframe: false,
      ...options
    }

    this.scene = null
    this.camera = null
    this.renderer = null
    this.controls = null
    this.artifactGroup = null
    this.bronzeModel = null
    this.riskParticles = null

    this.animationId = null
    this.clock = new THREE.Clock()

    this._init()
  }

  _init() {
    const width = this.container.clientWidth
    const height = this.container.clientHeight

    this.scene = new THREE.Scene()
    this.scene.background = new THREE.Color(this.options.backgroundColor)
    this.scene.fog = new THREE.FogExp2(this.options.backgroundColor, 0.08)

    this.camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000)
    this.camera.position.set(1.5, 1.2, 2.0)

    this.renderer = new THREE.WebGLRenderer({
      antialias: this.options.antialias,
      alpha: true
    })
    this.renderer.setPixelRatio(window.devicePixelRatio)
    this.renderer.setSize(width, height)
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.toneMappingExposure = 1.2
    this.container.appendChild(this.renderer.domElement)

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.05
    this.controls.minDistance = 0.5
    this.controls.maxDistance = 10
    this.controls.target.set(0, 0.2, 0)
    this.controls.autoRotate = this.options.autoRotate
    this.controls.autoRotateSpeed = 0.5

    this._setupLights()
    this._createGround()
    this._createArtifactGroup()

    this.riskParticles = new RiskParticles(this.artifactGroup, this.camera)
    this.bronzeModel = new BronzeModel({
      showWireframe: this.options.showWireframe
    })
    this.artifactGroup.add(this.bronzeModel.group)

    window.addEventListener('resize', () => this._onResize())
    this._animate()
  }

  _setupLights() {
    const ambient = new THREE.AmbientLight(0xffffff, 0.35)
    this.scene.add(ambient)

    const hemi = new THREE.HemisphereLight(0xffeebb, 0x112244, 0.5)
    this.scene.add(hemi)

    const keyLight = new THREE.DirectionalLight(0xfff4e0, 1.2)
    keyLight.position.set(3, 4, 2)
    keyLight.castShadow = true
    keyLight.shadow.mapSize.width = 2048
    keyLight.shadow.mapSize.height = 2048
    keyLight.shadow.camera.near = 0.1
    keyLight.shadow.camera.far = 20
    keyLight.shadow.camera.left = -3
    keyLight.shadow.camera.right = 3
    keyLight.shadow.camera.top = 3
    keyLight.shadow.camera.bottom = -3
    this.scene.add(keyLight)

    const rimLight = new THREE.DirectionalLight(0x4488ff, 0.4)
    rimLight.position.set(-2, 2, -3)
    this.scene.add(rimLight)

    const fillLight = new THREE.PointLight(0xffaa55, 0.6, 10)
    fillLight.position.set(-1, 1, 2)
    this.scene.add(fillLight)

    const spotLight = new THREE.SpotLight(0xffffff, 1.0)
    spotLight.position.set(0, 3, 0)
    spotLight.angle = Math.PI / 5
    spotLight.penumbra = 0.4
    spotLight.castShadow = true
    this.scene.add(spotLight)
  }

  _createGround() {
    const platformGeo = new THREE.CylinderGeometry(0.8, 0.9, 0.08, 64)
    const platformMat = new THREE.MeshStandardMaterial({
      color: 0x2a2018,
      roughness: 0.8,
      metalness: 0.2
    })
    const platform = new THREE.Mesh(platformGeo, platformMat)
    platform.position.y = -0.3
    platform.receiveShadow = true
    this.scene.add(platform)

    const ringGeo = new THREE.TorusGeometry(0.78, 0.01, 16, 128)
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xb87333,
      transparent: true,
      opacity: 0.6
    })
    const ring = new THREE.Mesh(ringGeo, ringMat)
    ring.rotation.x = -Math.PI / 2
    ring.position.y = -0.255
    this.scene.add(ring)
  }

  _createArtifactGroup() {
    this.artifactGroup = new THREE.Group()
    this.scene.add(this.artifactGroup)
  }

  buildBronzeDing(style = 'simsimuwu') {
    this.clearArtifact()
    this.bronzeModel.build(style)
    this.artifactGroup.add(this.bronzeModel.group)

    if (this.options.showWireframe) {
      this.bronzeModel.group.traverse(obj => {
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
  }

  clearArtifact() {
    if (!this.bronzeModel) return
    this.bronzeModel.group.removeFromParent()
    this.bronzeModel.clear()
    this.riskParticles.clearAll()
  }

  addRiskZone(options = {}) {
    return this.riskParticles.addRiskZone(options)
  }

  addEruptionParticles(options = {}) {
    return this.riskParticles.addEruption(options)
  }

  clearRiskZones() {
    this.riskParticles.clearRiskZones()
  }

  clearParticles() {
    this.riskParticles.clearParticles()
  }

  updateRiskZonesFromData(zones = []) {
    this.riskParticles.updateRiskZonesFromData(zones)
  }

  updateEruptionsFromData(eruptions = []) {
    this.riskParticles.updateEruptionsFromData(eruptions)
  }

  get riskZones() {
    return this.riskParticles.riskZones
  }

  get eruptionParticles() {
    return this.riskParticles.eruptionParticles
  }

  get instancedParticleSystems() {
    return this.riskParticles.instancedParticleSystems
  }

  get riskMaterials() {
    return this.riskParticles.riskMaterials
  }

  _animate = () => {
    this.animationId = requestAnimationFrame(this._animate)
    const delta = this.clock.getDelta()
    const elapsed = this.clock.getElapsedTime()

    this.controls.update()
    TWEEN.update()

    this.riskParticles.update(elapsed, delta)

    this.renderer.render(this.scene, this.camera)
  }

  _onResize() {
    const w = this.container.clientWidth
    const h = this.container.clientHeight
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(w, h)
  }

  setAutoRotate(enabled) {
    this.controls.autoRotate = enabled
  }

  resetCamera() {
    new TWEEN.Tween(this.camera.position)
      .to({ x: 1.5, y: 1.2, z: 2.0 }, 800)
      .easing(TWEEN.Easing.Cubic.InOut)
      .start()
    new TWEEN.Tween(this.controls.target)
      .to({ x: 0, y: 0.2, z: 0 }, 800)
      .easing(TWEEN.Easing.Cubic.InOut)
      .start()
  }

  showStats() {
    return this.riskParticles.getStats()
  }

  dispose() {
    if (this.animationId) cancelAnimationFrame(this.animationId)
    this.clearArtifact()
    window.removeEventListener('resize', () => this._onResize())
    this.controls?.dispose()
    this.renderer?.dispose()
    if (this.renderer?.domElement?.parentNode) {
      this.renderer.domElement.parentNode.removeChild(this.renderer.domElement)
    }
    this.bronzeModel?.dispose()
    this.riskParticles?.dispose()
  }
}

export default BronzeArtifactViewer
