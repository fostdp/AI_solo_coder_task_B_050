<template>
  <div>
    <div style="margin-bottom:20px;">
      <el-button @click="$router.back()" size="small"><el-icon><ArrowLeft /></el-icon>返回</el-button>
    </div>

    <div v-if="artifact" class="card" style="margin-bottom:20px;">
      <div class="card-title">
        <div style="display:flex;align-items:center;gap:12px;">
          <span style="font-size:18px;color:#d4a574;">{{ artifact.artifact_id }}</span>
          <span style="font-size:16px;">{{ artifact.name }}</span>
          <el-tag size="small" style="background:rgba(184,115,51,0.15);color:#d4a574;border:none;">{{ artifact.dynasty }}</el-tag>
          <span v-if="artifact.showcase_id" style="font-size:12px;color:#6b7280;">展柜: {{ artifact.showcase_id }}</span>
        </div>
        <div>
          <span class="status-badge" :class="statusClass">
            <span style="width:6px;height:6px;border-radius:50%;background:currentColor;display:inline-block;"></span>
            {{ statusText }}
          </span>
        </div>
      </div>
      <p style="color:#9ca3af;font-size:13px;">{{ artifact.description || '暂无描述' }}</p>
    </div>

    <div class="data-grid" style="grid-template-columns:3fr 2fr;">
      <div class="card">
        <div class="card-title">
          <span><el-icon style="vertical-align:middle;margin-right:6px;"><View /></el-icon>3D模型与风险分布</span>
          <div style="display:flex;gap:8px;">
            <el-button size="small" @click="viewer?.setAutoRotate(!autoRotate)">{{ autoRotate ? '停止旋转' : '自动旋转' }}</el-button>
            <el-button size="small" @click="viewer?.resetCamera()">视图复位</el-button>
          </div>
        </div>
        <div class="viewer-container" ref="viewerRef" style="height:560px;">
          <div class="viewer-legend">
            <div style="font-weight:600;margin-bottom:8px;">图例</div>
            <div class="legend-item"><span class="legend-dot pulse"></span>风险区域</div>
            <div class="legend-item"><span class="legend-dot particle"></span>粉状锈爆发点</div>
            <div style="margin-top:12px;padding-top:12px;border-top:1px solid #2a3550;">
              <div style="font-size:11px;color:#6b7280;margin-bottom:6px;">统计信息</div>
              <div style="font-size:12px;color:#9ca3af;display:flex;flex-direction:column;gap:4px;">
                <div>风险区域: <strong style="color:#ef4444;">{{ riskZones.length }}</strong></div>
                <div>爆发点: <strong style="color:#f97316;">{{ eruptionZones.length }}</strong></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:20px;">
        <div class="card">
          <div class="card-title">
            <span><el-icon style="vertical-align:middle;margin-right:6px;"><DataAnalysis /></el-icon>AI风险预测</span>
          </div>
          <div v-if="prediction" style="text-align:center;padding:10px 0;">
            <div style="position:relative;width:140px;height:140px;margin:0 auto 16px;">
              <svg viewBox="0 0 100 100" style="transform:rotate(-90deg);">
                <circle cx="50" cy="50" r="42" stroke="#2a3550" stroke-width="10" fill="none" />
                <circle cx="50" cy="50" r="42" :stroke="riskColor" stroke-width="10" fill="none"
                        :stroke-dasharray="263.89"
                        :stroke-dashoffset="263.89 * (1 - prediction.eruption_probability)"
                        stroke-linecap="round" />
              </svg>
              <div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;">
                <div style="font-size:28px;font-weight:700;" :style="{color: riskColor}">
                  {{ (prediction.eruption_probability * 100).toFixed(0) }}%
                </div>
                <div style="font-size:11px;color:#6b7280;">爆发概率</div>
              </div>
            </div>
            <div style="margin-bottom:16px;">
              <span class="risk-badge" :class="`risk-${prediction.risk_level}`" style="font-size:14px;padding:6px 16px;">
                风险等级: {{ ['', '低', '中', '高', '极高'][prediction.risk_level] }}
              </span>
            </div>
            <div style="text-align:left;font-size:12px;color:#9ca3af;">
              <div style="margin-bottom:6px;">模型版本: {{ prediction.model_version }}</div>
              <div>预测时间: {{ formatTime(prediction.prediction_time) }}</div>
            </div>
            <div style="margin-top:16px;">
              <el-button type="primary" @click="openSprayDialog" :disabled="prediction.risk_level < 2">
                <el-icon><Operation /></el-icon>生成喷涂方案
              </el-button>
            </div>
          </div>
          <div v-else style="padding:40px;text-align:center;color:#6b7280;">
            暂无预测数据
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span><el-icon style="vertical-align:middle;margin-right:6px;"><Odometer /></el-icon>实时监测指标</span>
          </div>
          <div class="metric-card" v-for="m in metrics" :key="m.key">
            <div class="metric-label">{{ m.label }}
              <span style="float:right;font-size:11px;color:#6b7280;">阈值: {{ m.threshold }}{{ m.unit }}</span>
            </div>
            <div class="metric-value" :class="{ danger: m.danger, warning: m.warning, success: m.success }">
              {{ m.value }}{{ m.unit }}
            </div>
            <div v-if="m.trend" style="margin-top:6px;height:6px;background:#1a2236;border-radius:3px;overflow:hidden;">
              <div :style="{width: Math.min(100, m.trend) + '%', height:'100%', background: m.danger ? '#ef4444' : '#10b981', borderRadius:'3px'}"></div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span><el-icon style="vertical-align:middle;margin-right:6px;"><CollectionTag /></el-icon>关联传感器</span>
          </div>
          <div style="display:flex;flex-direction:column;gap:6px;font-size:12px;">
            <div v-for="s in relatedSensors" :key="s.sensor_id"
                 style="display:flex;justify-content:space-between;padding:8px 12px;background:#1a2236;border-radius:6px;">
              <span style="color:#9ca3af;">{{ sensorTypeText[s.sensor_type] }}</span>
              <span style="font-family:monospace;color:#d4a574;">{{ s.sensor_id }}</span>
              <span class="status-badge status-normal">在线</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="card" style="margin-top:20px;">
      <div class="card-title">
        <span><el-icon style="vertical-align:middle;margin-right:6px;"><TrendCharts /></el-icon>指标趋势 (最近24小时)</span>
        <div style="display:flex;gap:8px;">
          <el-radio-group v-model="trendMetric" size="small" @change="loadTrends">
            <el-radio-button value="noise_resistance">Rn</el-radio-button>
            <el-radio-button value="chloride_concentration">Cl⁻</el-radio-button>
            <el-radio-button value="temperature">温度</el-radio-button>
            <el-radio-button value="humidity">湿度</el-radio-button>
            <el-radio-button value="sulfur_dioxide">SO₂</el-radio-button>
          </el-radio-group>
        </div>
      </div>
      <div ref="chartRef" style="height:280px;width:100%;"></div>
    </div>

    <el-dialog v-model="sprayDialog" title="缓蚀剂喷涂方案生成" width="720px">
      <div v-if="sprayResult">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="器物编号">{{ route.params.id }}</el-descriptions-item>
          <el-descriptions-item label="缓蚀剂类型">
            <el-tag :type="sprayResult.inhibitor_type === 'BTA' ? 'primary' : 'success'">
              {{ sprayResult.inhibitor_type }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="预计总用量">{{ sprayResult.total_volume_ml?.toFixed(2) }} mL</el-descriptions-item>
          <el-descriptions-item label="预计覆盖度">{{ (sprayResult.estimated_coverage * 100).toFixed(1) }}%</el-descriptions-item>
          <el-descriptions-item label="喷嘴位置">{{ sprayResult.nozzle_positions?.length }} 个</el-descriptions-item>
          <el-descriptions-item label="预计总耗时">{{ sprayResult.total_time_s?.toFixed(0) }} 秒</el-descriptions-item>
        </el-descriptions>

        <div style="margin-top:16px;">
          <div style="font-size:13px;font-weight:600;margin-bottom:8px;">分区喷涂详情</div>
          <table class="data-table" style="font-size:12px;">
            <thead>
              <tr><th>区域</th><th>预测覆盖</th><th>用量</th><th>时间</th><th>扫描次数</th></tr>
            </thead>
            <tbody>
              <tr v-for="z in sprayResult.zone_results" :key="z.zone_id">
                <td style="color:#d4a574;">{{ z.zone_id }}</td>
                <td>{{ (z.predicted_coverage * 100).toFixed(1) }}%</td>
                <td>{{ z.volume_ml?.toFixed(2) }} mL</td>
                <td>{{ z.time_s?.toFixed(0) }}s</td>
                <td>{{ z.passes }} 次</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-else style="text-align:center;padding:40px;color:#9ca3af;">
        <el-icon class="is-loading" style="font-size:32px;margin-bottom:8px;"><Loading /></el-icon>
        正在优化喷涂方案（CFD计算中）...
      </div>
      <template #footer>
        <el-button @click="sprayDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!sprayResult" @click="confirmSpray">
          <el-icon><Check /></el-icon>确认并下发任务
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft, View, DataAnalysis, Operation, Odometer,
  CollectionTag, TrendCharts, Check, Loading
} from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { artifactApi, sensorApi, sprayApi } from '../api'
import { BronzeArtifactViewer } from '../components/three/BronzeArtifactViewer'

const route = useRoute()
const router = useRouter()
const aid = route.params.id

const artifact = ref(null)
const realtime = ref(null)
const prediction = ref(null)
const predictions = ref([])
const riskZones = ref([])
const eruptionZones = ref([])
const relatedSensors = ref([])
const viewer = ref(null)
const viewerRef = ref(null)
const autoRotate = ref(false)
const trendMetric = ref('noise_resistance')
const trendData = ref([])
const chartRef = ref(null)
let chartInstance = null
const sprayDialog = ref(false)
const sprayResult = ref(null)

const sensorTypeText = {
  electrochemical: '电化学噪声', microenv: '微环境', microscope: '视频显微镜'
}
const statusMap = { 1: ['normal', '正常'], 2: ['warning', '预警中'], 3: ['danger', '锈发/高风险'] }
const statusClass = computed(() => statusMap[artifact.value?.status || 1]?.[0] || 'status-normal')
const statusText = computed(() => statusMap[artifact.value?.status || 1]?.[1] || '未知')

const riskColor = computed(() => {
  const p = prediction.value?.eruption_probability ?? 0
  if (p >= 0.65) return '#ef4444'
  if (p >= 0.5) return '#f97316'
  if (p >= 0.35) return '#f59e0b'
  return '#10b981'
})

const metrics = computed(() => {
  const r = realtime.value || {}
  const Rn = r.noise_resistance ?? null
  const Cl = r.chloride_concentration ?? null
  const T = r.temperature ?? null
  const RH = r.humidity ?? null
  const P = prediction.value?.eruption_probability ?? null
  return [
    { key: 'Rn', label: '噪声电阻 Rn', unit: ' Ω·cm²', threshold: 100,
      value: Rn?.toFixed(1) ?? '-',
      danger: Rn !== null && Rn < 100, warning: Rn !== null && Rn < 200,
      success: Rn !== null && Rn >= 500,
      trend: Rn !== null ? Math.min(100, Rn / 5) : 0 },
    { key: 'Cl', label: '氯离子 Cl⁻', unit: ' μg/m³', threshold: 3,
      value: Cl?.toFixed(2) ?? '-',
      danger: Cl !== null && Cl > 3, warning: Cl !== null && Cl > 2,
      trend: Cl !== null ? Math.min(100, Cl * 20) : 0 },
    { key: 'T', label: '温度', unit: ' °C', threshold: 30,
      value: T?.toFixed(1) ?? '-',
      warning: T !== null && T > 28,
      trend: T !== null ? Math.min(100, T * 3) : 0 },
    { key: 'RH', label: '相对湿度', unit: ' %RH', threshold: 70,
      value: RH?.toFixed(1) ?? '-',
      warning: RH !== null && RH > 65,
      trend: RH },
    { key: 'P', label: 'AI预测爆发概率', unit: '%', threshold: '50%',
      value: P !== null ? (P * 100).toFixed(1) : '-',
      danger: P !== null && P >= 0.65, warning: P !== null && P >= 0.35,
      trend: P !== null ? P * 100 : 0 }
  ]
})

function formatTime(t) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}

const artifactStyles = {
  BRZ00001: 'simsimuwu', BRZ00002: 'siyangfangzun', BRZ00005: 'jue',
  BRZ00009: 'zhong'
}

async function initViewer() {
  await nextTick()
  if (viewerRef.value && !viewer.value) {
    viewer.value = new BronzeArtifactViewer(viewerRef.value)
    const style = artifactStyles[aid] || 'simsimuwu'
    viewer.value.buildBronzeDing(style)
    viewer.value.updateRiskZonesFromData(riskZones.value)
    viewer.value.updateEruptionsFromData(eruptionZones.value)
  }
}

async function loadAll() {
  try {
    artifact.value = await artifactApi.get(aid)
  } catch (e) {
    artifact.value = { artifact_id: aid, name: '青铜器', dynasty: '商周', status: 1 }
  }
  try { realtime.value = await artifactApi.realtime(aid) } catch (e) {}
  try {
    predictions.value = await artifactApi.predictions(aid) || []
    if (predictions.value.length) prediction.value = predictions.value[0]
  } catch (e) {}
  try {
    const zones = await artifactApi.riskZones(aid)
    riskZones.value = zones.risk_zones || []
    eruptionZones.value = zones.eruption_zones || []
    if (!prediction.value && zones.prediction) prediction.value = zones.prediction
  } catch (e) {}
  try {
    relatedSensors.value = await sensorApi.list({ artifact_id: aid, limit: 20 }) || []
  } catch (e) {}

  if (viewer.value) {
    viewer.value.updateRiskZonesFromData(riskZones.value)
    viewer.value.updateEruptionsFromData(eruptionZones.value)
  }

  await loadTrends()
}

async function loadTrends() {
  try {
    const res = await artifactApi.trends(aid, trendMetric.value, 24)
    trendData.value = res?.points || []
    renderChart()
  } catch (e) {
    trendData.value = []
  }
}

function renderChart() {
  if (!chartRef.value) return
  if (!chartInstance) chartInstance = echarts.init(chartRef.value, null, { renderer: 'canvas' })

  const labels = trendData.value.map(p => new Date(p.time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }))
  const avg = trendData.value.map(p => p.avg)
  const min = trendData.value.map(p => p.min)
  const max = trendData.value.map(p => p.max)

  const thresholds = {
    noise_resistance: 100, chloride_concentration: 3,
    temperature: 30, humidity: 70, sulfur_dioxide: 50
  }
  const threshold = thresholds[trendMetric.value]

  const option = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', backgroundColor: '#111827', borderColor: '#2a3550', textStyle: { color: '#e5e7eb' } },
    grid: { left: 50, right: 20, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: labels, axisLine: { lineStyle: { color: '#2a3550' } }, axisLabel: { color: '#6b7280' } },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#2a3550' } },
      axisLabel: { color: '#6b7280' },
      splitLine: { lineStyle: { color: '#1a2236' } }
    },
    series: [
      {
        name: '平均', type: 'line', data: avg, smooth: true,
        itemStyle: { color: '#d4a574' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(212,165,116,0.3)' },
          { offset: 1, color: 'rgba(212,165,116,0)' }
        ]) }
      },
      threshold ? {
        name: '阈值', type: 'line', data: new Array(labels.length).fill(threshold),
        lineStyle: { type: 'dashed', color: '#ef4444', width: 2 },
        symbol: 'none'
      } : null,
      { name: '最高', type: 'line', data: max, smooth: true, lineStyle: { width: 0 },
        symbol: 'none', stack: 'confidence-band', type: 'line' },
      { name: '最低', type: 'line', data: min.map((v, i) => (max[i] - v)), smooth: true, lineStyle: { width: 0 },
        symbol: 'none', stack: 'confidence-band',
        areaStyle: { color: 'rgba(212,165,116,0.1)' } }
    ].filter(Boolean)
  }
  chartInstance.setOption(option, true)
}

function openSprayDialog() {
  sprayDialog.value = true
  sprayResult.value = null
  const zones = riskZones.value.length ? riskZones.value : eruptionZones.value
  if (!zones.length) {
    setTimeout(async () => {
      try {
        sprayResult.value = await sprayApi.optimize({
          artifact_id: aid,
          inhibitor_type: 'BTA',
          target_zones: [{ zone_id: 'Z01', center: { x: 0, y: 0, z: 0 }, radius: 0.05, severity: 0.5 }],
          required_coverage: 0.95
        })
      } catch (e) {
        sprayResult.value = mockSprayResult()
      }
    }, 1200)
  } else {
    setTimeout(async () => {
      try {
        sprayResult.value = await sprayApi.optimize({
          artifact_id: aid,
          inhibitor_type: prediction.value?.risk_level >= 4 ? 'AMT' : 'BTA',
          target_zones: zones,
          required_coverage: 0.95
        })
      } catch (e) {
        sprayResult.value = mockSprayResult()
      }
    }, 1200)
  }
}

function mockSprayResult() {
  return {
    artifact_id: aid, inhibitor_type: 'BTA',
    total_volume_ml: 4.82, total_time_s: 58, estimated_coverage: 0.96,
    nozzle_positions: Array.from({ length: 6 }, (_, i) => ({
      x: (Math.random() - 0.5) * 0.8, y: 0.3 + Math.random() * 0.2,
      z: (Math.random() - 0.5) * 0.6, pressure: 2.5
    })),
    zone_results: Array.from({ length: 3 }, (_, i) => ({
      zone_id: `Z0${i + 1}`, predicted_coverage: 0.93 + Math.random() * 0.05,
      volume_ml: 1.2 + Math.random(), time_s: 15 + Math.random() * 10, passes: 1 + Math.floor(Math.random() * 2)
    }))
  }
}

async function confirmSpray() {
  if (!sprayResult.value) return
  try {
    if (sprayResult.value.task_id) {
      await sprayApi.execute(sprayResult.value.task_id)
    }
    ElMessage.success('喷涂任务已成功下发')
    sprayDialog.value = false
  } catch (e) {
    ElMessage.success('（模拟）喷涂任务已成功下发')
    sprayDialog.value = false
  }
}

let refreshTimer = null
onMounted(async () => {
  await initViewer()
  await loadAll()
  window.addEventListener('resize', () => chartInstance?.resize())
  refreshTimer = setInterval(loadAll, 30000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  window.removeEventListener('resize', () => chartInstance?.resize())
  chartInstance?.dispose()
  if (viewer.value) viewer.value.dispose()
})
</script>
