import * as THREE from 'three'

export const PRODUCT_COLORS = {
  malachite: 0x228B22,
  atacamite: 0x7CFC00,
  cassiterite: 0x8B4513,
  cuprite: 0xB22222,
  azurite: 0x1E90FF,
  unknown: 0x808080
}

export const PRODUCT_NAMES = {
  malachite: '孔雀石',
  atacamite: '氯铜矿',
  cassiterite: '锡石',
  cuprite: '赤铜矿',
  azurite: '蓝铜矿',
  unknown: '未知'
}

export const VULN_COLOR_STOPS = [
  { t: 0.0, color: new THREE.Color(0x3B82F6) },
  { t: 0.25, color: new THREE.Color(0x10B981) },
  { t: 0.5, color: new THREE.Color(0xF59E0B) },
  { t: 0.75, color: new THREE.Color(0xF97316) },
  { t: 1.0, color: new THREE.Color(0xEF4444) }
]

export function getVulnerabilityColor(score) {
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

export const LIFE_STATUS_COLORS = {
  excellent: '#10B981',
  good: '#3B82F6',
  degrading: '#F59E0B',
  warning: '#F97316',
  expired: '#EF4444'
}

export const LIFE_STATUS_NAMES = {
  excellent: '优秀',
  good: '良好',
  degrading: '缓慢降解',
  warning: '警告',
  expired: '失效'
}
