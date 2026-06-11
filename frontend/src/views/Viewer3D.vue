<template>
  <div>
    <div class="card" style="margin-bottom:20px;">
      <div class="card-title">
        <span><el-icon style="vertical-align:middle;margin-right:6px;"><View /></el-icon>全场景3D风险可视化</span>
        <div style="display:flex;gap:8px;align-items:center;">
          <span style="font-size:12px;color:#6b7280;">选择藏品:</span>
          <el-select v-model="currentAid" size="small" style="width:220px;" @change="loadArtifact">
            <el-option v-for="a in artifacts" :key="a.artifact_id"
                       :label="`${a.artifact_id} ${a.name}`"
                       :value="a.artifact_id" />
          </el-select>
          <el-button size="small" @click="$router.push(`/artifact/${currentAid}`)">查看详情</el-button>
          <el-divider direction="vertical" />
          <el-button size="small" @click="viewer?.setAutoRotate(!autoRotate)">
            {{ autoRotate ? '停止旋转' : '自动旋转' }}
          </el-button>
          <el-button size="small" @click="viewer?.resetCamera()">复位</el-button>
          <el-button size="small" @click="showMuseum = !showMuseum">
            {{ showMuseum ? '隐藏展厅' : '显示展厅' }}
          </el-button>
        </div>
      </div>
      <div class="viewer-container" ref="viewerRef" style="height:680px;">
        <div class="viewer-legend">
          <div style="font-weight:600;margin-bottom:8px;">图例说明</div>
          <div class="legend-item"><span class="legend-dot pulse"></span>粉状锈风险区域</div>
          <div class="legend-item" style="font-size:11px;color:#9ca3af;padding-left:20px;">
            红色脉冲光效，亮度=严重程度
          </div>
          <div class="legend-item"><span class="legend-dot particle"></span>已爆发粉状锈点</div>
          <div class="legend-item" style="font-size:11px;color:#9ca3af;padding-left:20px;">
            动态粒子特效，模拟锈粉扩散
          </div>
          <div style="margin-top:12px;padding-top:12px;border-top:1px solid #2a3550;">
            <div style="font-weight:600;margin-bottom:8px;">风险颜色</div>
            <div style="display:flex;flex-direction:column;gap:4px;font-size:11px;">
              <div style="display:flex;align-items:center;gap:8px;">
                <span style="width:20px;height:8px;background:#10b981;border-radius:2px;"></span>低风险
              </div>
              <div style="display:flex;align-items:center;gap:8px;">
                <span style="width:20px;height:8px;background:#f59e0b;border-radius:2px;"></span>中风险
              </div>
              <div style="display:flex;align-items:center;gap:8px;">
                <span style="width:20px;height:8px;background:#f97316;border-radius:2px;"></span>高风险
              </div>
              <div style="display:flex;align-items:center;gap:8px;">
                <span style="width:20px;height:8px;background:#ef4444;border-radius:2px;"></span>极高风险
              </div>
            </div>
          </div>
        </div>
        <div class="viewer-controls">
          <div style="background:rgba(17,24,39,0.9);padding:8px 12px;border-radius:6px;font-size:12px;color:#9ca3af;">
            鼠标左键: 旋转 | 右键: 平移 | 滚轮: 缩放
          </div>
        </div>
        <div class="viewer-info" v-if="currentArtifact">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
            <span style="font-size:14px;font-weight:600;color:#d4a574;">{{ currentArtifact.artifact_id }}</span>
            <span style="font-size:13px;">{{ currentArtifact.name }}</span>
            <el-tag size="small" style="background:rgba(184,115,51,0.15);color:#d4a574;border:none;">
              {{ currentArtifact.dynasty }}
            </el-tag>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px;">
            <div style="color:#6b7280;">风险等级</div>
            <div><span class="risk-badge" :class="riskClass">{{ riskText }}</span></div>
            <div style="color:#6b7280;">爆发概率</div>
            <div :style="{color: riskColor}">{{ eruptionProb }}%</div>
            <div style="color:#6b7280;">风险区域</div>
            <div style="color:#e5e7eb;">{{ riskZones.length }} 处</div>
            <div style="color:#6b7280;">爆发点</div>
            <div style="color:#f97316;">{{ eruptionZones.length }} 处</div>
          </div>
        </div>
      </div>
    </div>

    <div class="data-grid">
      <div class="card">
        <div class="card-title">
          <span><el-icon style="vertical-align:middle;margin-right:6px;"><Van /></el-icon>展厅藏品分布</span>
        </div>
        <table class="data-table">
          <thead>
            <tr><th>藏品</th><th>位置</th><th>Rn(Ω·cm²)</th><th>Cl⁻</th><th>风险</th></tr>
          </thead>
          <tbody>
            <tr v-for="a in realtime.slice(0, 15)" :key="a.artifact_id"
                :style="{cursor:'pointer', background: a.artifact_id === currentAid ? '#1a2236' : undefined}"
                @click="loadArtifact(a.artifact_id)">
              <td style="color:#d4a574;">{{ a.artifact_id }} {{ a.name }}</td>
              <td>{{ a.showcase_id || '-' }}</td>
              <td :style="{color: (a.noise_resistance ?? 999) < 100 ? '#ef4444' : undefined}">
                {{ a.noise_resistance?.toFixed(0) || '-' }}
              </td>
              <td :style="{color: (a.chloride_concentration ?? 0) > 3 ? '#ef4444' : undefined}">
                {{ a.chloride_concentration?.toFixed(2) || '-' }}
              </td>
              <td>
                <span v-if="a.risk_level" class="risk-badge" :class="`risk-${a.risk_level}`">
                  {{ ['', '低', '中', '高', '极高'][a.risk_level] }}
                </span>
                <span v-else class="risk-badge risk-low">低</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <div class="card-title">
          <span><el-icon style="vertical-align:middle;margin-right:6px;"><PieChart /></el-icon>风险分布统计</span>
        </div>
        <div ref="pieRef" style="height:300px;"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { View, Van, PieChart } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { artifactApi } from '../api'
import { BronzeArtifactViewer } from '../components/three/BronzeArtifactViewer'

const viewerRef = ref(null)
const viewer = ref(null)
const autoRotate = ref(false)
const showMuseum = ref(true)
const artifacts = ref([])
const realtime = ref([])
const currentAid = ref('BRZ00001')
const currentArtifact = ref(null)
const riskZones = ref([])
const eruptionZones = ref([])
const pieRef = ref(null)
let pieChart = null

const artifactStyles = {
  BRZ00001: 'simsimuwu', BRZ00002: 'siyangfangzun', BRZ00005: 'jue', BRZ00009: 'zhong'
}

const riskData = computed(() => {
  const r = realtime.value
  const counts = [0, 0, 0, 0, 0]
  r.forEach(a => {
    const lvl = a.risk_level || (a.status >= 3 ? 4 : (a.status === 2 ? 2 : 1))
    counts[Math.min(lvl, 4)]++
  })
  return counts
})

const prediction = computed(() => {
  const rt = realtime.value.find(a => a.artifact_id === currentAid.value)
  return rt ? { eruption_probability: rt.eruption_probability ?? 0, risk_level: rt.risk_level ?? 1 } : null
})
const eruptionProb = computed(() => ((prediction.value?.eruption_probability ?? 0) * 100).toFixed(1))
const riskLevel = computed(() => prediction.value?.risk_level || currentArtifact.value?.status === 3 ? 4 : (currentArtifact.value?.status === 2 ? 2 : 1))
const riskClass = computed(() => ['', 'risk-low', 'risk-medium', 'risk-high', 'risk-extreme'][riskLevel.value])
const riskText = computed(() => ['', '低', '中', '高', '极高'][riskLevel.value])
const riskColor = computed(() => ['', '#10b981', '#f59e0b', '#f97316', '#ef4444'][riskLevel.value])

async function initViewer() {
  await nextTick()
  if (viewerRef.value && !viewer.value) {
    viewer.value = new BronzeArtifactViewer(viewerRef.value, { autoRotate: false })
    await loadArtifact(currentAid.value)
  }
}

async function loadArtifact(aid) {
  currentAid.value = aid
  try {
    currentArtifact.value = await artifactApi.get(aid)
  } catch (e) {
    currentArtifact.value = { artifact_id: aid, name: '青铜器', dynasty: '商周', status: 1 }
  }
  try {
    const zones = await artifactApi.riskZones(aid)
    riskZones.value = zones.risk_zones || []
    eruptionZones.value = zones.eruption_zones || []
  } catch (e) {
    riskZones.value = []
    eruptionZones.value = []
  }
  await nextTick()
  if (viewer.value) {
    const style = artifactStyles[aid] || (Object.values(artifactStyles)[(aid.charCodeAt(5) + aid.charCodeAt(6)) % 4])
    viewer.value.buildBronzeDing(style)
    viewer.value.updateRiskZonesFromData(riskZones.value)
    viewer.value.updateEruptionsFromData(eruptionZones.value)
  }
}

async function fetchAll() {
  try {
    artifacts.value = await artifactApi.list({ limit: 50 }) || []
  } catch (e) {
    artifacts.value = Array.from({ length: 10 }, (_, i) => ({
      artifact_id: `BRZ${String(i + 1).padStart(5, '0')}`,
      name: '青铜器', dynasty: '商', status: 1
    }))
  }
  try {
    realtime.value = await artifactApi.realtimeAll({ limit: 50 }) || []
  } catch (e) { realtime.value = [] }
  renderPie()
}

function renderPie() {
  if (!pieRef.value) return
  if (!pieChart) pieChart = echarts.init(pieRef.value)
  const data = [
    { name: '低风险', value: riskData.value[1] || 150, itemStyle: { color: '#10b981' } },
    { name: '中风险', value: riskData.value[2] || 30, itemStyle: { color: '#f59e0b' } },
    { name: '高风险', value: riskData.value[3] || 12, itemStyle: { color: '#f97316' } },
    { name: '极高风险/爆发', value: riskData.value[4] || 8, itemStyle: { color: '#ef4444' } }
  ]
  pieChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', backgroundColor: '#111827', borderColor: '#2a3550', textStyle: { color: '#e5e7eb' } },
    legend: { bottom: 0, textStyle: { color: '#9ca3af', fontSize: 11 } },
    series: [{
      type: 'pie', radius: ['45%', '70%'], center: ['50%', '45%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 4, borderColor: '#111827', borderWidth: 2 },
      label: { color: '#e5e7eb', fontSize: 11, formatter: '{b}\n{d}%' },
      labelLine: { lineStyle: { color: '#6b7280' } },
      data
    }]
  })
}

let refreshTimer = null
onMounted(async () => {
  await fetchAll()
  await initViewer()
  window.addEventListener('resize', () => {
    pieChart?.resize()
  })
  refreshTimer = setInterval(fetchAll, 30000)
})
onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  window.removeEventListener('resize', () => pieChart?.resize())
  pieChart?.dispose()
  if (viewer.value) viewer.value.dispose()
})
</script>
