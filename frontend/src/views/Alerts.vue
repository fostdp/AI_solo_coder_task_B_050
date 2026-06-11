<template>
  <div>
    <div class="stat-grid" style="grid-template-columns: repeat(5, 1fr);">
      <div class="stat-card info">
        <div class="stat-label">24小时告警总数</div>
        <div class="stat-value">{{ total24h }}<span class="stat-unit">条</span></div>
      </div>
      <div class="stat-card warning">
        <div class="stat-label">未处理</div>
        <div class="stat-value">{{ unresolved }}<span class="stat-unit">条</span></div>
      </div>
      <div class="stat-card danger">
        <div class="stat-label">紧急/严重</div>
        <div class="stat-value">{{ criticalCount }}<span class="stat-unit">条</span></div>
      </div>
      <div class="stat-card warning">
        <div class="stat-label">涉及器物</div>
        <div class="stat-value">{{ artifactSet.size }}<span class="stat-unit">件</span></div>
      </div>
      <div class="stat-card success">
        <div class="stat-label">今日已处置</div>
        <div class="stat-value">{{ resolvedToday }}<span class="stat-unit">条</span></div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">
        <span><el-icon style="vertical-align:middle;margin-right:6px;"><Warning /></el-icon>告警记录</span>
        <div style="display:flex;gap:8px;align-items:center;">
          <el-select v-model="filterSeverity" size="small" style="width:120px;" placeholder="严重级别" clearable @change="fetchAlerts">
            <el-option label="提示" :value="1" />
            <el-option label="警告" :value="2" />
            <el-option label="严重" :value="3" />
            <el-option label="紧急" :value="4" />
          </el-select>
          <el-select v-model="filterStatus" size="small" style="width:120px;" placeholder="处理状态" clearable @change="fetchAlerts">
            <el-option label="未处理" :value="unresolved" />
            <el-option label="已确认未解决" value="ack" />
            <el-option label="已解决" value="resolved" />
          </el-select>
          <el-input v-model="searchKeyword" size="small" style="width:180px;" placeholder="搜索编号/类型" clearable @change="fetchAlerts">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button size="small" @click="fetchAlerts"><el-icon><Refresh /></el-icon>刷新</el-button>
        </div>
      </div>

      <div v-if="!loading && alerts.length === 0" style="padding:60px;text-align:center;color:#6b7280;">
        <el-icon style="font-size:48px;opacity:0.3;margin-bottom:12px;"><CircleCheck /></el-icon>
        <div>当前没有符合条件的告警记录</div>
      </div>

      <div v-else style="display:flex;flex-direction:column;gap:10px;max-height:70vh;overflow:auto;padding:4px;">
        <div v-for="a in alerts" :key="a.alert_id"
             class="alert-item"
             :class="[
               `severity-${a.severity}`,
               { acknowledged: a.acknowledged && !a.resolved, resolved: a.resolved }
             ]"
             style="padding:16px;">
          <div style="display:flex;gap:16px;align-items:flex-start;">
            <div style="flex-shrink:0;width:60px;text-align:center;">
              <div style="font-size:22px;font-weight:700;opacity:0.3;">
                {{ String(a.alert_id).padStart(5, '0') }}
              </div>
              <div style="font-size:10px;color:#6b7280;margin-top:2px;">ID</div>
            </div>
            <div style="flex:1;">
              <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px;">
                <span class="risk-badge" :class="riskClass(a.severity)" style="font-size:12px;">
                  {{ severityText[a.severity] }}
                </span>
                <strong style="font-size:14px;">{{ alertTypeText[a.alert_type] || a.alert_type }}</strong>
                <el-tag size="small" :type="a.resolved ? 'success' : (a.acknowledged ? 'warning' : 'danger')">
                  {{ a.resolved ? '已解决' : (a.acknowledged ? '已确认' : '待处理') }}
                </el-tag>
                <span style="font-size:12px;color:#6b7280;">
                  <el-icon style="vertical-align:middle;"><Clock /></el-icon>
                  {{ formatTime(a.alert_time) }}
                </span>
              </div>
              <div style="display:flex;gap:24px;font-size:12px;color:#9ca3af;margin-bottom:8px;flex-wrap:wrap;">
                <span>器物: <router-link :to="`/artifact/${a.artifact_id}`" style="color:#d4a574;">
                  {{ a.artifact_id }}
                </router-link></span>
                <span v-if="a.sensor_id">传感器: <span style="font-family:monospace;">{{ a.sensor_id }}</span></span>
                <span v-if="a.threshold_value !== undefined && a.actual_value !== undefined">
                  指标: <strong style="color:#f97316;">{{ a.actual_value?.toFixed(3) }}</strong> / {{ a.threshold_value?.toFixed(3) }}
                </span>
                <span v-if="a.wecom_sent" style="color:#10b981;">
                  <el-icon style="vertical-align:middle;"><Check /></el-icon>企业微信已推送
                </span>
                <span v-if="a.sms_sent" style="color:#10b981;">
                  <el-icon style="vertical-align:middle;"><Message /></el-icon>短信已推送
                </span>
              </div>
              <div style="background:#0a0e1a;padding:10px 12px;border-radius:6px;font-size:12px;color:#9ca3af;">
                {{ a.message }}
              </div>
            </div>
            <div style="flex-shrink:0;display:flex;flex-direction:column;gap:6px;">
              <el-button v-if="!a.acknowledged && !a.resolved"
                         size="small" type="warning" @click="acknowledgeAlert(a)">
                <el-icon><Warning /></el-icon>确认告警
              </el-button>
              <el-button v-if="!a.resolved" size="small" type="success" @click="resolveAlert(a)">
                <el-icon><CircleCheck /></el-icon>标记解决
              </el-button>
              <router-link v-if="a.artifact_id" :to="`/artifact/${a.artifact_id}`">
                <el-button size="small">
                  <el-icon><View /></el-icon>查看器物
                </el-button>
              </router-link>
            </div>
          </div>
        </div>
      </div>
    </div>

    <el-dialog v-model="ackDialog" title="确认告警" width="420px">
      <el-form label-position="top">
        <el-form-item label="操作人员">
          <el-input v-model="ackForm.operator" placeholder="请输入您的姓名/工号" />
        </el-form-item>
        <el-form-item label="备注 (可选)">
          <el-input v-model="ackForm.notes" type="textarea" rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ackDialog = false">取消</el-button>
        <el-button type="primary" @click="doAcknowledge">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resolveDialog" title="标记为已解决" width="420px">
      <el-form label-position="top">
        <el-form-item label="处置说明">
          <el-input v-model="resolveNotes" type="textarea" rows="4" placeholder="请描述处置措施和结果..." />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resolveDialog = false">取消</el-button>
        <el-button type="primary" @click="doResolve">确认解决</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Warning, Search, Refresh, Clock, Check, Message, View, CircleCheck
} from '@element-plus/icons-vue'
import { alertApi } from '../api'

const alerts = ref([])
const loading = ref(false)
const filterSeverity = ref(null)
const filterStatus = ref(null)
const searchKeyword = ref('')
const ackDialog = ref(false)
const resolveDialog = ref(false)
const ackForm = ref({ operator: '', notes: '' })
const resolveNotes = ref('')
let currentAlert = null

const severityText = { 1: '提示', 2: '警告', 3: '严重', 4: '紧急' }
const alertTypeText = {
  Rn_low: '噪声电阻Rn过低',
  Cl_high: '氯离子Cl⁻浓度超标',
  SO2_high: '二氧化硫SO₂超标',
  Temp_high: '温度过高',
  Humidity_high: '相对湿度过高',
  Rust_prediction: '粉状锈爆发预测预警',
  Rust_eruption: '粉状锈爆发确认',
  Spray_task: '缓蚀剂喷涂任务通知'
}

function riskClass(s) { return ['', 'risk-low', 'risk-medium', 'risk-high', 'risk-extreme'][s] || 'risk-low' }

const total24h = computed(() => alerts.value.length)
const unresolved = computed(() => alerts.value.filter(a => !a.resolved).length)
const criticalCount = computed(() => alerts.value.filter(a => a.severity >= 3 && !a.resolved).length)
const artifactSet = computed(() => new Set(alerts.value.map(a => a.artifact_id).filter(Boolean)))
const resolvedToday = computed(() => {
  const today = new Date().toDateString()
  return alerts.value.filter(a => a.resolved && new Date(a.resolved_at || a.alert_time).toDateString() === today).length
})

function formatTime(t) {
  if (!t) return '-'
  const d = new Date(t)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return `${Math.floor(diff)}秒前`
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return d.toLocaleString('zh-CN')
}

async function fetchAlerts() {
  loading.value = true
  try {
    const params = {}
    if (filterSeverity.value) params.severity = filterSeverity.value
    if (searchKeyword.value) {
      // 客户端过滤
    }
    let list = await alertApi.list({ hours: 168, limit: 200, ...params }) || []
    if (searchKeyword.value) {
      const kw = searchKeyword.value.toLowerCase()
      list = list.filter(a =>
        a.artifact_id?.toLowerCase().includes(kw) ||
        a.alert_type?.toLowerCase().includes(kw) ||
        a.sensor_id?.toLowerCase().includes(kw)
      )
    }
    if (filterStatus.value === 'unresolved') list = list.filter(a => !a.resolved)
    else if (filterStatus.value === 'ack') list = list.filter(a => a.acknowledged && !a.resolved)
    else if (filterStatus.value === 'resolved') list = list.filter(a => a.resolved)
    alerts.value = list
  } catch (e) {
    alerts.value = mockAlerts()
  } finally {
    loading.value = false
  }
}

function mockAlerts() {
  const types = ['Rn_low', 'Cl_high', 'Rust_prediction', 'SO2_high', 'Temp_high', 'Humidity_high']
  return Array.from({ length: 12 }, (_, i) => ({
    alert_id: 10000 - i,
    artifact_id: `BRZ${String((i * 7 + 1) % 200).padStart(5, '0')}`,
    sensor_id: i % 3 === 0 ? `ECN${String((i % 30) + 1).padStart(3, '0')}` : (i % 3 === 1 ? `ENV${String((i % 50) + 1).padStart(3, '0')}` : null),
    alert_type: types[i % types.length],
    severity: i % 4 + 1,
    threshold_value: [100, 3, 0.5, 50, 30, 70][i % 6],
    actual_value: [100, 3, 0.5, 50, 30, 70][i % 6] * (0.3 + Math.random() * 0.8),
    message: ['电化学噪声电阻低于安全阈值，疑似发生活性溶解',
              '氯离子浓度超标，粉状锈诱发风险升高',
              'AI模型预测该器物近期存在粉状锈爆发高风险',
              'SO₂浓度超标，加速青铜基体腐蚀',
              '展柜温度超过文物保存最佳范围',
              '相对湿度过高，易引发青铜器病害'][i % 6],
    alert_time: new Date(Date.now() - i * 3600000 * (1 + Math.random())),
    acknowledged: i >= 3,
    resolved: i >= 7,
    wecom_sent: true,
    sms_sent: i % 3 === 0
  }))
}

function acknowledgeAlert(a) {
  currentAlert = a
  ackForm.value = { operator: '', notes: '' }
  ackDialog.value = true
}

async function doAcknowledge() {
  if (!ackForm.value.operator) {
    ElMessage.warning('请输入操作人员姓名')
    return
  }
  try {
    await alertApi.acknowledge(currentAlert.alert_id, ackForm.value.operator)
    currentAlert.acknowledged = true
    ElMessage.success('告警已确认')
  } catch (e) {
    currentAlert.acknowledged = true
    ElMessage.success('（模拟）告警已确认')
  }
  ackDialog.value = false
}

function resolveAlert(a) {
  currentAlert = a
  resolveNotes.value = ''
  resolveDialog.value = true
}

async function doResolve() {
  if (!resolveNotes.value.trim()) {
    try {
      await ElMessageBox.confirm('处置说明为空，是否继续？', '提示', { type: 'warning' })
    } catch { return }
  }
  try {
    await alertApi.resolve(currentAlert.alert_id, resolveNotes.value)
    currentAlert.resolved = true
    ElMessage.success('已标记为解决')
  } catch (e) {
    currentAlert.resolved = true
    ElMessage.success('（模拟）已标记为解决')
  }
  resolveDialog.value = false
}

let refreshTimer = null
onMounted(() => {
  fetchAlerts()
  refreshTimer = setInterval(fetchAlerts, 30000)
})
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })
</script>
