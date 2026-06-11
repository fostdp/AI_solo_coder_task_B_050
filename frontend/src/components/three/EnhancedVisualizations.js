import * as THREE from 'three'
import { PRODUCT_COLORS, PRODUCT_NAMES, VULN_COLOR_STOPS, getVulnerabilityColor } from './constants.js'
import { RamanMarkers3D, RamanLegend } from './RamanLegend.js'
import { SprayPathTrajectory, SprayPath } from './SprayPath.js'
import { VulnerabilityHeatmap } from './VulnerabilityHeatmap.js'
import { LifetimeBadges3D, LifeTimer } from './LifeTimer.js'

export {
  PRODUCT_COLORS,
  PRODUCT_NAMES,
  VULN_COLOR_STOPS,
  getVulnerabilityColor,
  RamanMarkers3D,
  RamanLegend,
  SprayPathTrajectory,
  SprayPath,
  VulnerabilityHeatmap,
  LifetimeBadges3D,
  LifeTimer
}

export default {
  RamanMarkers3D,
  RamanLegend,
  SprayPathTrajectory,
  SprayPath,
  VulnerabilityHeatmap,
  LifetimeBadges3D,
  LifeTimer,
  PRODUCT_COLORS,
  PRODUCT_NAMES,
  VULN_COLOR_STOPS,
  getVulnerabilityColor
}
