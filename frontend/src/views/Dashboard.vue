<template>
  <div>
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">藏品总数</div>
        <div class="stat-value">{{ stats.total_artifacts }}<span class="stat-unit">件</span></div>
        <div class="stat-trend">商周青铜器馆藏</div>
      </div>
      <div class="stat-card success">
        <div class="stat-label">状态正常</div>
        <div class="stat-value">{{ stats.normal_count }}<span class="stat-unit">件</span></div>
        <div class="stat-trend" v-if="stats.total_artifacts">
          占比 {{ (stats.normal_count / stats.total_artifacts * 100).toFixed(1) }}%
        </div>
      </div>
      <div class="stat-card warning">
        <div class="stat-label">预警中</div>
        <div class="stat-value">{{ stats.warning_count }}<span class="stat-unit">件</span></div>
        <div class="stat-trend">需持续关注</div>
      </div>
      <div class="stat-card danger">
        <div class="stat-label">高风险/爆发</div>
        <div class="stat-value">{{ stats.alert_count + eruptionEstimate }}<span class="stat-unit">件</span></div>
        <div class="stat-trend">需紧急处理</div>
      </div>
      <div class="stat-card info">
        <div class="stat-label">平均噪声电阻</div>
        <div class="stat-value" :class="{ danger: stats.avg_noise_resistance < 100 }">
          {{ stats.avg_noise_resistance?.toFixed(1) }}
          <span class="stat-unit">Ω·cm²</span>
        </div>
        <div class="stat-trend" :style="{ color: stats.avg_noise_resistance < 100 ? '#ef4444' : undefined }">
          阈值: 100 Ω·cm²
        </div>
      </div>
      <div class="stat-card danger">
        <div class="stat-label">平均Cl⁻浓度</div>
        <div class="stat-value" :class="{ danger: stats.avg_chloride > 3 }">
          {{ stats.avg_chloride?.toFixed(2) }}
          <span class="stat-unit">μg/m³</span>
        </div>
        <div class="stat-trend" :style="{ color: stats.avg_chloride > 3 ? '#ef4444' : undefined }">
          阈值: 3 μg/m³
        </div>
      </div>
      <div class="stat-card warning">
        <div class="stat-label">24h告警</div>
        <div class="stat-value">{{ stats.active_alerts_24h }}<span class="stat-unit">条</span></div>
        <div class="stat-trend">未处理</div>
      </div>
      <div class="stat-card info">
        <div class="stat-label">喷涂任务</div>
        <div class="stat-value">{{ stats.spray_tasks_pending }}<span class="stat-unit">项</span></div>
        <div class="stat-trend">待执行/执行中</div>
      </div>
    </div>

    <div class="data-grid">
      <div class="card" style="min-height:500px;">
        <div class="card-title">
          <span><el-icon style="vertical-align:middle;margin-right:6px;"><View /></el-icon>3D风险监测视图</span>
          <div style="display:flex;gap:8px;">
            <el-select v-model="selectedArtifact" size="small" style="width:200px;" @change="onArtifactChange">
              <el-option v-for="a in artifactList" :key="a.artifact_id"
                         :label="`${a.artifact_id} ${a.name}`"
                         :value="a.artifact_id" />
            </el-select>
            <el-button size="small" @click="$router.push(`/artifact/${selectedArtifact}`)">查看详情</el-button>
          </div>
        </div>
        <div class="viewer-container" ref="viewerRef">
          <div class="viewer-legend">
            <div style="font-weight:600;margin-bottom:6px;color:#e5e7eb;">图例</div>
            <div class="legend-item"><span class="legend-dot pulse"></span><span>风险区域（脉冲光效）</span></div>
            <div class="legend-item"><span class="legend-dot particle"></span><span>已爆发点（粒子特效）</span></div>
          </div>
          <div class="viewer-controls">
            <el-button size="small" @click="viewer?.setAutoRotate(!autoRotate)">
              <el-icon><RefreshRight /></el-icon>{{ autoRotate ? '停止' : '旋转' }}
            </el-button>
            <el-button size="small" @click="viewer?.resetCamera()">
              <el-icon><Aim /></el-icon>复位
            </el-button>
          </div>
          <div class="viewer-info" v-if="riskInfo">
            <div style="font-weight:600;margin-bottom:6px;">风险评估</div>
            <div style="display:flex;flex-direction:column;gap:4px;color:#9ca3af;">
              <div>爆发概率: <span :style="{color: riskColor}">
                {{ (riskInfo.eruption_probability * 100).toFixed(1) }}%
              </span></div>
              <div>风险等级: <span :class="`risk-badge risk-${riskLevelClass}`">{{ riskLevelText }}</span></div>
              <div>风险区域: {{ riskZones.length }} 处，爆发点: {{ eruptionZones.length }} 处</div>
            </div>
          </div>
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:20px;">
        <div class="card">
          <div class="card-title">
            <span><el-icon style="vertical-align:middle;margin-right:6px;"><Warning /></el-icon>最新告警</span>
            <router-link to="/alerts" style="font-size:12px;color:#d4a574;">查看全部 →</router-link>
          </div>
          <div v-if="!alerts.length" style="padding:24px;text-align:center;color:#6b7280;">
            <el-icon style="font-size:36px;opacity:0.3;margin-bottom:8px;"><CircleCheck /></el-icon>
            暂无告警数据
          </div>
          <div v-else>
            <div v-for="a in alerts.slice(0, 6)" :key="a.alert_id"
                 class="alert-item" :class="[`severity-${a.severity}`, { acknowledged: a.acknowledged, resolved: a.resolved }]">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div style="flex:1;">
                  <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                    <span class="risk-badge" :class="`risk-${riskLevelMap[a.severity]}`">
                      {{ severityText[a.severity] }}
                    </span>
                    <strong style="color:#e5e7eb;">{{ a.artifact_id }}</strong>
                    <span style="font-size:11px;color:#6b7280;">{{ alertTypeText[a.alert_type] || a.alert_type }}</span>
                  </div>
                  <div style="font-size:12px;color:#9ca3af;">{{ a.message }}</div>
                  <div style="font-size:11px;color:#6b7280;margin-top:4px;">
                    {{ formatTime(a.alert_time) }}
                    <span v-if="a.actual_value !== undefined && a.threshold_value !== undefined" style="margin-left:12px;">
                      当前: <strong style="color:#f97316;">{{ a.actual_value?.toFixed(3) }}</strong> /
                      阈值: {{ a.threshold_value?.toFixed(3) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span><el-icon style="vertical-align:middle;margin-right:6px;"><DataBoard /></el-icon>高风险器物</span>
          </div>
          <table class="data-table" style="font-size:12px;">
            <thead>
              <tr>
                <th>编号</th><th>名称</th><th>朝代</th><th>Rn</th><th>Cl⁻</th><th>风险</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in highRiskArtifacts" :key="a.artifact_id"
                  :style="{cursor:'pointer'}"
                  @click="$router.push(`/artifact/${a.artifact_id}`)">
                <td style="color:#d4a574;">{{ a.artifact_id }}</td>
                <td>{{ a.name }}</td>
                <td>{{ a.dynasty }}</td>
                <td :style="{color: (a.noise_resistance ?? 999) < 100 ? '#ef4444' : undefined}">
                  {{ a.noise_resistance?.toFixed(0) }}
                </td>
                <td :style="{color: (a.chloride_concentration ?? 0) > 3 ? '#ef4444' : undefined}">
                  {{ a.chloride_concentration?.toFixed(2) }}
                </td>
                <td>
                  <span v-if="a.risk_level" class="risk-badge" :class="`risk-${a.risk_level}`">
                    {{ ['', '低', '中', '高', '极高'][a.risk_level] }}
                  </span>
                  <span v-else-if="a.status >= 2" class="risk-badge risk-high">中</span>
                  <span v-else class="risk-badge risk-low">低</span>
                </td>
              </tr>
              <tr v-if="!highRiskArtifacts.length">
                <td colspan="6" style="padding:20px;text-align:center;color:#6b7280;">暂无高风险器物</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed, nextTick } from 'vue'
import {
  View, Warning, DataBoard, CircleCheck, RefreshRight, Aim
} from '@element-plus/icons-vue'
import { statsApi, artifactApi, alertApi } from '../api'
import { BronzeArtifactViewer } from '../components/three/BronzeArtifactViewer'

const stats = ref({})
const alerts = ref([])
const artifactList = ref([])
const realtimeList = ref([])
const selectedArtifact = ref('BRZ00001')
const viewer = ref(null)
const viewerRef = ref(null)
const autoRotate = ref(false)
const riskInfo = ref(null)
const riskZones = ref([])
const eruptionZones = ref([])

const eruptionEstimate = computed(() => stats.value.eruption_count || 0)
const riskLevelMap = { 1: 'low', 2: 'medium', 3: 'high', 4: 'extreme' }
const severityText = { 1: '提示', 2: '警告', 3: '严重', 4: '紧急' }
const alertTypeText = {
  Rn_low: '噪声电阻过低', Cl_high: 'Cl⁻超标', SO2_high: 'SO₂超标',
  Temp_high: '温度过高', Humidity_high: '湿度过高',
  Rust_prediction: '锈发预警', Rust_eruption: '锈发确认', Spray_task: '喷涂任务'
}

const riskColor = computed(() => {
  const p = riskInfo.value?.eruption_probability ?? 0
  if (p >= 0.65) return '#ef4444'
  if (p >= 0.5) return '#f97316'
  if (p >= 0.35) return '#f59e0b'
  return '#10b981'
})
const riskLevelClass = computed(() => riskLevelMap[riskInfo.value?.risk_level] || 'low')
const riskLevelText = computed(() => ['', '低', '中', '高', '极高'][riskInfo.value?.risk_level] || '低')

const highRiskArtifacts = computed(() =>
  realtimeList.value
    .filter(a => (a.status >= 2) || (a.risk_level >= 3) ||
                 (a.noise_resistance && a.noise_resistance < 100) ||
                 (a.chloride_concentration && a.chloride_concentration > 3))
    .sort((a, b) => (b.status - a.status) || (a.noise_resistance || 9999) - (b.noise_resistance || 9999))
    .slice(0, 8)
)

function formatTime(t) {
  if (!t) return ''
  const d = new Date(t)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return `${Math.floor(diff)}秒前`
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const artifactStyles = {
  BRZ00001: 'simsimuwu', BRZ00002: 'siyangfangzun', BRZ00005: 'jue',
  BRZ00009: 'zhong', BRZ00003: 'simsimuwu', BRZ00004: 'jue',
  BRZ00006: 'simsimuwu', BRZ00007: 'simsimuwu', BRZ00008: 'simsimuwu'
}

async function initViewer() {
  await nextTick()
  if (viewerRef.value && !viewer.value) {
    viewer.value = new BronzeArtifactViewer(viewerRef.value, { autoRotate: false })
    await loadArtifactData(selectedArtifact.value)
  }
}

async function loadArtifactData(aid) {
  try {
    const zones = await artifactApi.riskZones(aid)
    riskInfo.value = zones.prediction
    riskZones.value = zones.risk_zones || []
    eruptionZones.value = zones.eruption_zones || []
    await nextTick()
    if (viewer.value) {
      const style = artifactStyles[aid] || (Object.values(artifactStyles)[(aid.charCodeAt(5) + aid.charCodeAt(6)) % 5])
      viewer.value.buildBronzeDing(style)
      viewer.value.updateRiskZonesFromData(riskZones.value)
      viewer.value.updateEruptionsFromData(eruptionZones.value)
    }
  } catch (e) {
    if (viewer.value) {
      viewer.value.buildBronzeDing('simsimuwu')
    }
  }
}

async function onArtifactChange(aid) {
  await loadArtifactData(aid)
}

async function fetchAll() {
  try {
    stats.value = await statsApi.get() || {}
  } catch (e) { stats.value = defaultStats() }
  try {
    artifactList.value = await artifactApi.list({ limit: 200 }) || []
  } catch (e) { artifactList.value = mockArtifacts() }
  try {
    realtimeList.value = await artifactApi.realtimeAll({ limit: 200 }) || []
  } catch (e) { realtimeList.value = [] }
  try {
    alerts.value = await alertApi.list({ hours: 24, limit: 20 }) || []
  } catch (e) { alerts.value = [] }
}

function defaultStats() {
  return {
    total_artifacts: 200, normal_count: 185, warning_count: 10, alert_count: 4,
    active_alerts_24h: 7, spray_tasks_pending: 2,
    avg_noise_resistance: 342.8, avg_chloride: 1.87,
    sensors_online: 100, sensors_total: 100, predictions_today: 186
  }
}
function mockArtifacts() {
  return Array.from({ length: 10 }, (_, i) => ({
    artifact_id: `BRZ${String(i + 1).padStart(5, '0')}`,
    name: ['司母戊鼎', '四羊方尊', '大克鼎', '毛公鼎', '散氏盘', '何尊', '虢季子白盘', '连珠纹斝', '兽面纹爵', '饕餮纹方鼎'][i],
    dynasty: ['商', '商', '西周', '西周', '西周', '西周', '西周', '商', '商', '商'][i],
    status: i < 2 ? 1 : (i < 5 ? 2 : 3)
  }))
}

let refreshTimer = null

onMounted(async () => {
  await fetchAll()
  await initViewer()
  refreshTimer = setInterval(fetchAll, 30000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (viewer.value) viewer.value.dispose()
})
</script>
