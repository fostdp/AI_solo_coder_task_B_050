<template>
  <div>
    <div class="stat-grid" style="grid-template-columns: repeat(4, 1fr);">
      <div class="stat-card info">
        <div class="stat-label">喷涂任务总数</div>
        <div class="stat-value">{{ tasks.length }}<span class="stat-unit">项</span></div>
      </div>
      <div class="stat-card warning">
        <div class="stat-label">待执行</div>
        <div class="stat-value">{{ pendingCount }}<span class="stat-unit">项</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-label">执行中</div>
        <div class="stat-value">{{ runningCount }}<span class="stat-unit">项</span></div>
      </div>
      <div class="stat-card success">
        <div class="stat-label">已完成</div>
        <div class="stat-value">{{ completedCount }}<span class="stat-unit">项</span></div>
      </div>
    </div>

    <div class="data-grid">
      <div class="card">
        <div class="card-title">
          <span><el-icon style="vertical-align:middle;margin-right:6px;"><Operation /></el-icon>喷涂任务列表</span>
          <el-button type="primary" size="small" @click="newTaskDialog = true">
            <el-icon style="vertical-align:middle;margin-right:4px;"><Plus /></el-icon>
            新建喷涂任务
          </el-button>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>任务ID</th><th>器物</th><th>缓蚀剂</th><th>预计用量</th><th>覆盖度</th><th>状态</th><th>创建时间</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in tasks" :key="t.task_id">
              <td style="color:#d4a574;font-family:monospace;">#{{ t.task_id }}</td>
              <td>
                <router-link :to="`/artifact/${t.artifact_id}`" style="color:#e5e7eb;">
                  {{ t.artifact_id }}
                </router-link>
                <el-tag v-if="t.alert_id" size="small" type="danger" style="margin-left:6px;">
                  关联告警
                </el-tag>
              </td>
              <td>
                <el-tag :type="inhibitorTagClass(t.inhibitor_type)" size="small" style="border:none;">
                  {{ t.inhibitor_type }}
                </el-tag>
              </td>
              <td>{{ t.total_volume?.toFixed(2) || '-' }} mL</td>
              <td>
                <div style="display:flex;align-items:center;gap:8px;">
                  <el-progress :percentage="Math.round((t.coverage_estimate || 0) * 100)"
                               :color="coverageColor(t.coverage_estimate)"
                               :stroke-width="6" :show-text="false" style="width:80px;" />
                  <span style="font-size:12px;">{{ ((t.coverage_estimate || 0) * 100).toFixed(0) }}%</span>
                </div>
              </td>
              <td>
                <el-tag size="small" :type="statusTagType(t.status)" effect="light">
                  {{ statusText[t.status] }}
                </el-tag>
              </td>
              <td style="font-size:12px;color:#6b7280;">{{ formatTime(t.created_at) }}</td>
              <td>
                <div style="display:flex;gap:4px;">
                  <el-button size="small" @click="viewTask(t)">
                    <el-icon><View /></el-icon>
                  </el-button>
                  <el-button v-if="t.status === 0" size="small" type="primary" @click="executeTask(t)">
                    <el-icon><VideoPlay /></el-icon>
                  </el-button>
                </div>
              </td>
            </tr>
            <tr v-if="tasks.length === 0">
              <td colspan="8" style="padding:40px;text-align:center;color:#6b7280;">暂无任务记录</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div style="display:flex;flex-direction:column;gap:20px;">
        <div class="card">
          <div class="card-title">
            <span><el-icon style="vertical-align:middle;margin-right:6px;"><Collection /></el-icon>缓蚀剂选型指南</span>
          </div>
          <div style="display:flex;flex-direction:column;gap:12px;">
            <div v-for="inh in inhibitors" :key="inh.type"
                 style="padding:12px;border-radius:8px;border:1px solid var(--border-color);background:#0a0e1a;">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                <span style="width:12px;height:12px;border-radius:50%;"
                      :style="{background: inh.color, boxShadow:`0 0 8px ${inh.color}`}"></span>
                <strong style="font-size:14px;">{{ inh.type }}</strong>
                <span style="font-size:11px;color:#6b7280;">{{ inh.name }}</span>
              </div>
              <div style="font-size:12px;color:#9ca3af;display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;">
                <div>分子量: {{ inh.mw }} g/mol</div>
                <div>推荐浓度: {{ inh.conc }} mM</div>
                <div>吸附效率: {{ inh.adsorption }}%</div>
                <div>适用场景: {{ inh.scene }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span><el-icon style="vertical-align:middle;margin-right:6px;"><DataAnalysis /></el-icon>喷涂效果统计</span>
          </div>
          <div ref="chartRef" style="height:240px;"></div>
        </div>
      </div>
    </div>

    <el-dialog v-model="newTaskDialog" title="新建缓蚀剂喷涂任务" width="640px">
      <el-form label-width="100px">
        <el-form-item label="目标器物">
          <el-select v-model="newTask.artifact_id" filterable style="width:100%;">
            <el-option v-for="a in artifacts" :key="a.artifact_id"
                       :label="`${a.artifact_id} ${a.name}`"
                       :value="a.artifact_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联告警ID">
          <el-input-number v-model="newTask.alert_id" :min="0" />
        </el-form-item>
        <el-form-item label="缓蚀剂类型">
          <el-radio-group v-model="newTask.inhibitor_type">
            <el-radio-button v-for="i in inhibitors" :key="i.type" :value="i.type">{{ i.type }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="目标区域">
          <div style="width:100%;display:flex;flex-direction:column;gap:6px;">
            <div v-for="(z, idx) in newTask.target_zones" :key="idx"
                 style="display:flex;gap:6px;align-items:center;">
              <el-input v-model="z.zone_id" placeholder="区域ID" style="width:100px;" size="small" />
              <span style="font-size:12px;color:#6b7280;">X</span>
              <el-input-number v-model="z.center.x" :precision="3" :step="0.01" size="small" style="width:120px;" />
              <span style="font-size:12px;color:#6b7280;">Y</span>
              <el-input-number v-model="z.center.y" :precision="3" :step="0.01" size="small" style="width:120px;" />
              <span style="font-size:12px;color:#6b7280;">Z</span>
              <el-input-number v-model="z.center.z" :precision="3" :step="0.01" size="small" style="width:120px;" />
              <span style="font-size:12px;color:#6b7280;">R</span>
              <el-input-number v-model="z.radius" :precision="3" :step="0.01" size="small" style="width:100px;" />
              <el-button size="small" type="danger" text @click="newTask.target_zones.splice(idx, 1)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-button size="small" @click="newTask.target_zones.push(defaultZone())">
              <el-icon><Plus /></el-icon>添加区域
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="覆盖要求">
          <el-slider v-model="newTask.required_coverage" :min="0.5" :max="0.99" :step="0.01"
                     :format-tooltip="v => `${Math.round(v*100)}%`" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newTaskDialog = false">取消</el-button>
        <el-button type="primary" @click="optimizeAndCreate">
          <el-icon style="vertical-align:middle;margin-right:4px;"><MagicStick /></el-icon>
          CFD优化并生成方案
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailDialog" title="喷涂任务详情" width="720px">
      <div v-if="currentTask">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="任务ID">#{{ currentTask.task_id }}</el-descriptions-item>
          <el-descriptions-item label="器物">{{ currentTask.artifact_id }}</el-descriptions-item>
          <el-descriptions-item label="缓蚀剂">{{ currentTask.inhibitor_type }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="statusTagType(currentTask.status)">{{ statusText[currentTask.status] }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="预计用量">{{ currentTask.total_volume?.toFixed(2) }} mL</el-descriptions-item>
          <el-descriptions-item label="预计覆盖度">{{ ((currentTask.coverage_estimate || 0) * 100).toFixed(1) }}%</el-descriptions-item>
          <el-descriptions-item label="实际用量">{{ currentTask.actual_volume?.toFixed(2) || '-' }} mL</el-descriptions-item>
          <el-descriptions-item label="实际覆盖度">{{ currentTask.actual_coverage ? (currentTask.actual_coverage*100).toFixed(1)+'%' : '-' }}</el-descriptions-item>
        </el-descriptions>

        <div style="margin-top:16px;" v-if="plan.zone_results?.length">
          <div style="font-size:13px;font-weight:600;margin-bottom:8px;">分区喷涂方案</div>
          <table class="data-table" style="font-size:12px;">
            <thead><tr><th>区域</th><th>中心坐标</th><th>预测覆盖</th><th>用量</th><th>耗时</th><th>扫描次数</th></tr></thead>
            <tbody>
              <tr v-for="z in plan.zone_results" :key="z.zone_id">
                <td style="color:#d4a574;">{{ z.zone_id }}</td>
                <td style="font-size:11px;font-family:monospace;">
                  ({{ z.center?.x?.toFixed(2) }}, {{ z.center?.y?.toFixed(2) }}, {{ z.center?.z?.toFixed(2) }})
                </td>
                <td>{{ (z.predicted_coverage * 100).toFixed(1) }}%</td>
                <td>{{ z.volume_ml?.toFixed(2) }} mL</td>
                <td>{{ z.time_s?.toFixed(0) }}s</td>
                <td>{{ z.passes }} 次</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div style="margin-top:16px;" v-if="plan.nozzle_positions?.length">
          <div style="font-size:13px;font-weight:600;margin-bottom:8px;">喷嘴路径 ({{ plan.nozzle_positions.length }} 个位置)</div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;font-size:11px;font-family:monospace;">
            <div v-for="(n, i) in plan.nozzle_positions" :key="i"
                 style="background:#0a0e1a;padding:8px;border-radius:4px;border:1px solid #2a3550;">
              <div style="color:#9ca3af;margin-bottom:4px;">喷嘴 #{{ i + 1 }}</div>
              <div>X: {{ n.x?.toFixed(3) }}</div>
              <div>Y: {{ n.y?.toFixed(3) }}</div>
              <div>Z: {{ n.z?.toFixed(3) }}</div>
              <div>P: {{ n.pressure?.toFixed(1) }} bar</div>
            </div>
          </div>
        </div>

        <div style="margin-top:16px;padding:12px;background:#0a0e1a;border-radius:6px;font-size:12px;color:#9ca3af;"
             v-if="plan.cfd_summary">
          <div style="font-weight:600;margin-bottom:6px;color:#e5e7eb;">CFD模拟摘要</div>
          <div v-for="(v, k) in plan.cfd_summary" :key="k" style="display:flex;justify-content:space-between;">
            <span>{{ k }}</span><span>{{ typeof v === 'number' ? v.toFixed(3) : v }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="detailDialog = false">关闭</el-button>
        <el-button v-if="currentTask?.status === 0" type="primary" @click="executeTask(currentTask)">
          <el-icon><VideoPlay /></el-icon>执行喷涂
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, nextTick, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Operation, Plus, View, VideoPlay, Collection, DataAnalysis,
  Delete, MagicStick
} from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { sprayApi, artifactApi } from '../api'

const tasks = ref([])
const artifacts = ref([])
const newTaskDialog = ref(false)
const detailDialog = ref(false)
const currentTask = ref(null)
const plan = ref({})
const chartRef = ref(null)
let chart = null

const newTask = ref({
  artifact_id: 'BRZ00001',
  alert_id: null,
  inhibitor_type: 'BTA',
  target_zones: [{ zone_id: 'Z01', center: { x: 0, y: 0, z: 0 }, radius: 0.05, severity: 0.7 }],
  required_coverage: 0.95
})

const inhibitors = [
  { type: 'BTA', name: '苯并三氮唑', mw: 119.12, conc: 10, adsorption: 85,
    scene: '常规预防性保护', color: '#00aaff' },
  { type: 'AMT', name: '2-氨基-5-巯基-1,3,4-噻二唑', mw: 150.22, conc: 15, adsorption: 92,
    scene: '高Cl⁻污染环境', color: '#00ff88' },
  { type: 'MBO', name: '2-巯基苯并恶唑', mw: 150.22, conc: 8, adsorption: 95,
    scene: '已有爆发点，高风险', color: '#ffaa00' }
]

const statusText = { 0: '待执行', 1: '执行中', 2: '已完成', 3: '已取消' }

const pendingCount = computed(() => tasks.value.filter(t => t.status === 0).length)
const runningCount = computed(() => tasks.value.filter(t => t.status === 1).length)
const completedCount = computed(() => tasks.value.filter(t => t.status === 2).length)

function inhibitorTagClass(t) {
  return t === 'BTA' ? 'primary' : t === 'AMT' ? 'success' : 'warning'
}
function statusTagType(s) {
  return ['info', 'warning', 'success', 'info'][s] || 'info'
}
function coverageColor(c) {
  c = c || 0
  if (c >= 0.95) return '#10b981'
  if (c >= 0.85) return '#f59e0b'
  return '#ef4444'
}
function defaultZone() {
  return {
    zone_id: `Z${String(newTask.value.target_zones.length + 1).padStart(2, '0')}`,
    center: { x: (Math.random() - 0.5) * 0.5, y: Math.random() * 0.2, z: (Math.random() - 0.5) * 0.3 },
    radius: 0.03 + Math.random() * 0.06,
    severity: 0.5 + Math.random() * 0.4
  }
}
function formatTime(t) {
  return t ? new Date(t).toLocaleString('zh-CN') : '-'
}

async function fetchTasks() {
  try {
    tasks.value = await sprayApi.list({ limit: 50 }) || []
  } catch (e) {
    tasks.value = mockTasks()
  }
  renderChart()
}
async function fetchArtifacts() {
  try {
    artifacts.value = await artifactApi.list({ limit: 100 }) || []
  } catch (e) {
    artifacts.value = Array.from({ length: 10 }, (_, i) => ({
      artifact_id: `BRZ${String(i + 1).padStart(5, '0')}`,
      name: ['司母戊鼎', '四羊方尊', '大克鼎', '毛公鼎', '散氏盘', '何尊', '连珠纹斝', '兽面纹爵', '虢盘', '铜钟'][i]
    }))
  }
}

function mockTasks() {
  const types = ['BTA', 'AMT', 'MBO']
  return Array.from({ length: 8 }, (_, i) => ({
    task_id: 1000 - i,
    artifact_id: `BRZ${String((i * 13 + 1) % 200).padStart(5, '0')}`,
    alert_id: i % 2 === 0 ? 1000 - i : null,
    inhibitor_type: types[i % 3],
    concentration: [10, 15, 8][i % 3],
    total_volume: 3 + Math.random() * 8,
    coverage_estimate: 0.88 + Math.random() * 0.1,
    status: i < 2 ? 0 : (i < 4 ? 1 : 2),
    scheduled_at: new Date(),
    started_at: i >= 2 ? new Date(Date.now() - 3600000) : null,
    completed_at: i >= 4 ? new Date() : null,
    actual_volume: i >= 4 ? (3 + Math.random() * 8) : null,
    actual_coverage: i >= 4 ? (0.88 + Math.random() * 0.1) : null,
    created_at: new Date(Date.now() - i * 86400000)
  }))
}

function viewTask(t) {
  currentTask.value = t
  plan.value = t.spray_plan || {
    zone_results: Array.from({ length: 3 }, (_, i) => ({
      zone_id: `Z0${i + 1}`, center: { x: 0, y: 0, z: 0 },
      predicted_coverage: 0.9 + Math.random() * 0.08,
      volume_ml: 1 + Math.random() * 2,
      time_s: 10 + Math.random() * 20,
      passes: 1 + Math.floor(Math.random() * 2)
    })),
    nozzle_positions: Array.from({ length: 6 }, () => ({
      x: (Math.random() - 0.5) * 0.8,
      y: 0.2 + Math.random() * 0.3,
      z: (Math.random() - 0.5) * 0.6,
      pressure: 2 + Math.random()
    })),
    cfd_summary: {
      droplet_mean_diameter_um: 45 + Math.random() * 10,
      deposition_efficiency: 0.8 + Math.random() * 0.15,
      evaporation_rate_coeff: 0.02 + Math.random() * 0.01,
      nozzle_candidates_evaluated: 64
    }
  }
  detailDialog.value = true
}

async function executeTask(t) {
  try {
    await sprayApi.execute(t.task_id)
    t.status = 1
    ElMessage.success('喷涂任务已启动，正在执行中...')
    setTimeout(() => { t.status = 2; t.completed_at = new Date() }, 8000)
  } catch (e) {
    t.status = 1
    ElMessage.success('（模拟）喷涂任务已启动')
    setTimeout(() => { t.status = 2 }, 8000)
  }
}

async function optimizeAndCreate() {
  if (!newTask.value.artifact_id) {
    ElMessage.warning('请选择目标器物')
    return
  }
  if (!newTask.value.target_zones.length) {
    ElMessage.warning('请添加至少一个目标区域')
    return
  }
  try {
    const result = await sprayApi.optimize(newTask.value)
    tasks.value.unshift({
      task_id: Math.floor(Math.random() * 9000) + 1000,
      artifact_id: newTask.value.artifact_id,
      alert_id: newTask.value.alert_id,
      inhibitor_type: newTask.value.inhibitor_type,
      total_volume: result.total_volume_ml,
      coverage_estimate: result.estimated_coverage,
      spray_plan: result,
      status: 0,
      created_at: new Date()
    })
    ElMessage.success('喷涂方案已生成')
    newTaskDialog.value = false
    newTask.value = {
      artifact_id: 'BRZ00001', alert_id: null, inhibitor_type: 'BTA',
      target_zones: [{ zone_id: 'Z01', center: { x: 0, y: 0, z: 0 }, radius: 0.05, severity: 0.7 }],
      required_coverage: 0.95
    }
  } catch (e) {
    tasks.value.unshift({
      task_id: Date.now() % 10000,
      artifact_id: newTask.value.artifact_id,
      alert_id: newTask.value.alert_id,
      inhibitor_type: newTask.value.inhibitor_type,
      total_volume: 5.82,
      coverage_estimate: 0.96,
      status: 0,
      created_at: new Date()
    })
    ElMessage.success('（模拟）喷涂方案已生成')
    newTaskDialog.value = false
  }
}

function renderChart() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  const data = [
    { value: tasks.value.filter(t => t.inhibitor_type === 'BTA').length, name: 'BTA', itemStyle: { color: '#00aaff' } },
    { value: tasks.value.filter(t => t.inhibitor_type === 'AMT').length, name: 'AMT', itemStyle: { color: '#00ff88' } },
    { value: tasks.value.filter(t => t.inhibitor_type === 'MBO').length, name: 'MBO', itemStyle: { color: '#ffaa00' } }
  ]
  if (data.every(d => d.value === 0)) data[0].value = 5
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', backgroundColor: '#111827', borderColor: '#2a3550', textStyle: { color: '#e5e7eb' } },
    legend: { bottom: 0, textStyle: { color: '#9ca3af' } },
    series: [{
      type: 'pie', radius: ['40%', '65%'], center: ['50%', '45%'],
      itemStyle: { borderRadius: 4, borderColor: '#111827', borderWidth: 2 },
      label: { color: '#e5e7eb', formatter: '{b}: {c}项' },
      data
    }]
  })
}

let timer = null
onMounted(async () => {
  await fetchTasks()
  await fetchArtifacts()
  await nextTick()
  renderChart()
  window.addEventListener('resize', () => chart?.resize())
  timer = setInterval(fetchTasks, 30000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('resize', () => chart?.resize())
  chart?.dispose()
})
</script>
