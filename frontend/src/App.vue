<template>
  <div class="app-layout">
    <header class="app-header">
      <div class="app-title">
        <div class="logo">鼎</div>
        <div>
          <div>古代青铜器粉状锈爆发预警与缓蚀剂智能喷涂系统</div>
          <div style="font-size:11px;color:#6b7280;font-weight:400;margin-top:2px;">Bronze Powdery Rust Early Warning & Inhibitor Intelligent Spray System</div>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:20px;">
        <div style="font-size:13px;color:#9ca3af;">
          <el-icon style="vertical-align:middle;margin-right:4px;"><Clock /></el-icon>
          {{ currentTime }}
        </div>
        <el-tag :type="wsConnected ? 'success' : 'info'" size="small">
          {{ wsConnected ? '● 实时连接' : '○ 离线模式' }}
        </el-tag>
        <el-tag type="warning" size="small">
          <el-icon style="vertical-align:middle;margin-right:4px;"><Bell /></el-icon>
          {{ activeAlerts }} 条告警
        </el-tag>
      </div>
    </header>

    <div class="app-main">
      <aside class="app-sidebar">
        <ul class="nav-menu">
          <li v-for="item in navItems" :key="item.path">
            <router-link :to="item.path" :class="{ active: route.path === item.path }">
              <el-icon><component :is="item.icon" /></el-icon>
              <span>{{ item.label }}</span>
            </router-link>
          </li>
        </ul>

        <div style="padding:20px 16px;margin-top:20px;border-top:1px solid var(--border-color);">
          <div style="font-size:11px;color:#6b7280;margin-bottom:10px;letter-spacing:1px;">传感器概览</div>
          <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;">
            <div style="display:flex;justify-content:space-between;color:#9ca3af;">
              <span>电化学噪声</span><span style="color:#3b82f6;">30/30</span>
            </div>
            <div style="display:flex;justify-content:space-between;color:#9ca3af;">
              <span>微环境监测</span><span style="color:#10b981;">50/50</span>
            </div>
            <div style="display:flex;justify-content:space-between;color:#9ca3af;">
              <span>视频显微镜</span><span style="color:#f59e0b;">20/20</span>
            </div>
          </div>
        </div>
      </aside>

      <main class="app-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { Clock, Bell, DataAnalysis, View, Warning, Operation, List } from '@element-plus/icons-vue'
import { alertApi } from './api'

const route = useRoute()
const currentTime = ref('')
const wsConnected = ref(false)
const activeAlerts = ref(0)

const navItems = [
  { path: '/', label: '总览仪表盘', icon: DataAnalysis },
  { path: '/viewer', label: '3D可视化', icon: View },
  { path: '/artifacts', label: '藏品管理', icon: List },
  { path: '/alerts', label: '告警中心', icon: Warning },
  { path: '/spray', label: '缓蚀剂喷涂', icon: Operation }
]

let timer = null
let alertTimer = null

function updateTime() {
  const now = new Date()
  currentTime.value = now.toLocaleString('zh-CN', { hour12: false })
}

async function fetchActiveAlerts() {
  try {
    const list = await alertApi.list({ resolved: false, hours: 24 })
    activeAlerts.value = list?.length || 0
  } catch (e) { /* ignore */ }
}

onMounted(() => {
  updateTime()
  timer = setInterval(updateTime, 1000)
  fetchActiveAlerts()
  alertTimer = setInterval(fetchActiveAlerts, 30000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (alertTimer) clearInterval(alertTimer)
})
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
