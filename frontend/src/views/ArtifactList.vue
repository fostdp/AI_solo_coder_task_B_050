<template>
  <div>
    <div class="card" style="margin-bottom:20px;">
      <div class="card-title">
        <span><el-icon style="vertical-align:middle;margin-right:6px;"><List /></el-icon>青铜器藏品管理</span>
        <div style="display:flex;gap:10px;align-items:center;">
          <el-select v-model="filterDynasty" size="small" style="width:120px;" clearable placeholder="朝代" @change="fetchList">
            <el-option v-for="d in dynasties" :key="d" :label="d" :value="d" />
          </el-select>
          <el-select v-model="filterStatus" size="small" style="width:120px;" clearable placeholder="状态" @change="fetchList">
            <el-option label="正常" :value="1" />
            <el-option label="预警" :value="2" />
            <el-option label="高风险/爆发" :value="3" />
          </el-select>
          <el-input v-model="keyword" size="small" style="width:240px;" placeholder="搜索编号/名称" clearable @change="fetchList">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button size="small" @click="fetchList"><el-icon><Refresh /></el-icon></el-button>
        </div>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>编号</th><th>名称</th><th>朝代</th><th>位置/展柜</th>
            <th>噪声电阻</th><th>Cl⁻浓度</th><th>AI风险</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in mergedList" :key="a.artifact_id"
              :style="{cursor:'pointer', background: a.status === 3 ? 'rgba(239,68,68,0.05)' : (a.status === 2 ? 'rgba(245,158,11,0.04)' : undefined)}"
              @click="goDetail(a.artifact_id)">
            <td style="color:#d4a574;font-family:monospace;font-weight:500;">{{ a.artifact_id }}</td>
            <td style="font-weight:500;">{{ a.name }}</td>
            <td>
              <el-tag size="small" style="background:rgba(184,115,51,0.12);color:#d4a574;border:none;">
                {{ a.dynasty }}
              </el-tag>
            </td>
            <td style="font-size:12px;color:#9ca3af;">
              {{ a.location || '-' }}
              <span v-if="a.showcase_id" style="color:#6b7280;"> · {{ a.showcase_id }}</span>
            </td>
            <td :style="{color: (a.noise_resistance ?? 999) < 100 ? '#ef4444' : undefined}">
              {{ a.noise_resistance?.toFixed(0) || '-' }}
              <span v-if="a.noise_resistance" style="font-size:10px;color:#6b7280;">Ω</span>
            </td>
            <td :style="{color: (a.chloride_concentration ?? 0) > 3 ? '#ef4444' : undefined}">
              {{ a.chloride_concentration?.toFixed(2) || '-' }}
              <span v-if="a.chloride_concentration" style="font-size:10px;color:#6b7280;">μg/m³</span>
            </td>
            <td>
              <span v-if="a.risk_level" class="risk-badge" :class="`risk-${a.risk_level}`">
                {{ ['', '低', '中', '高', '极高'][a.risk_level] }}
                <span v-if="a.eruption_probability !== undefined && a.eruption_probability !== null">
                  {{ (a.eruption_probability * 100).toFixed(0) }}%
                </span>
              </span>
              <span v-else class="risk-badge risk-low">-</span>
            </td>
            <td>
              <span class="status-badge" :class="statusClass(a.status)">
                {{ statusText(a.status) }}
              </span>
            </td>
            <td @click.stop>
              <div style="display:flex;gap:4px;">
                <el-button size="small" @click="goDetail(a.artifact_id)">
                  <el-icon><View /></el-icon>详情
                </el-button>
                <router-link :to="{ path: '/viewer', query: { aid: a.artifact_id } }">
                  <el-button size="small" type="primary">
                    <el-icon><Van /></el-icon>3D
                  </el-button>
                </router-link>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <div style="margin-top:16px;display:flex;justify-content:space-between;align-items:center;">
        <div style="font-size:12px;color:#6b7280;">
          共 {{ total }} 件 · 正常 {{ statNormal }} · 预警 {{ statWarning }} · 高风险 {{ statAlert }}
        </div>
        <el-pagination
          background layout="prev, pager, next"
          :total="total" :page-size="pageSize" v-model:current-page="page"
          @current-change="fetchList"
          style="--el-pagination-hover-bg-color: #1a2236;--el-pagination-bg-color: #111827;--el-pagination-text-color:#9ca3af;"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { List, Search, Refresh, View, Van } from '@element-plus/icons-vue'
import { artifactApi } from '../api'

const router = useRouter()
const dynasties = ['商', '西周', '东周', '春秋', '战国']
const filterDynasty = ref(null)
const filterStatus = ref(null)
const keyword = ref('')
const page = ref(1)
const pageSize = 20
const total = ref(200)

const artifactList = ref([])
const realtimeMap = ref({})

const mergedList = computed(() => {
  return artifactList.value.map(a => ({
    ...a,
    ...(realtimeMap.value[a.artifact_id] || {})
  }))
})

const statNormal = computed(() => mergedList.value.filter(a => a.status === 1).length)
const statWarning = computed(() => mergedList.value.filter(a => a.status === 2).length)
const statAlert = computed(() => mergedList.value.filter(a => a.status === 3).length)

function statusClass(s) {
  return ['', 'status-normal', 'status-warning', 'status-eruption'][s] || 'status-normal'
}
function statusText(s) {
  return ['', '正常', '预警中', '高风险'][s] || '正常'
}

async function fetchList() {
  try {
    const params = { skip: (page.value - 1) * pageSize, limit: pageSize }
    if (filterDynasty.value) params.dynasty = filterDynasty.value
    if (filterStatus.value !== null && filterStatus.value !== undefined) params.status = filterStatus.value
    if (keyword.value) params.keyword = keyword.value
    artifactList.value = await artifactApi.list(params) || []

    const rt = await artifactApi.realtimeAll({ limit: pageSize * 2 }) || []
    realtimeMap.value = {}
    rt.forEach(r => { realtimeMap.value[r.artifact_id] = r })

    if (!artifactList.value.length) {
      artifactList.value = mockArtifacts()
    }
  } catch (e) {
    artifactList.value = mockArtifacts()
  }
}

function mockArtifacts() {
  const names = ['司母戊鼎', '四羊方尊', '大克鼎', '毛公鼎', '散氏盘', '何尊', '虢季子白盘',
                 '连珠纹斝', '兽面纹爵', '饕餮纹方鼎', '莲鹤方壶', '曾侯乙编钟']
  return Array.from({ length: pageSize }, (_, i) => {
    const idx = (page.value - 1) * pageSize + i + 1
    const status = Math.random() > 0.9 ? 3 : (Math.random() > 0.8 ? 2 : 1)
    return {
      artifact_id: `BRZ${String(idx).padStart(5, '0')}`,
      name: names[i % names.length] + (idx > names.length ? ` #${idx}` : ''),
      dynasty: dynasties[idx % dynasties.length],
      location: ['一号展厅', '二号展厅', '三号展厅', '四号展厅'][idx % 4],
      showcase_id: `SC-${String.fromCharCode(65 + (idx % 8))}${String((idx % 20) + 1).padStart(2, '0')}`,
      status,
      noise_resistance: status === 3 ? Math.random() * 80 + 20 : (status === 2 ? Math.random() * 150 + 80 : Math.random() * 500 + 200),
      chloride_concentration: status >= 2 ? Math.random() * 6 + 1.5 : Math.random() * 2 + 0.3,
      risk_level: status,
      eruption_probability: status === 3 ? Math.random() * 0.4 + 0.6 : (status === 2 ? Math.random() * 0.3 + 0.35 : Math.random() * 0.3)
    }
  })
}

function goDetail(id) {
  router.push(`/artifact/${id}`)
}

let timer = null
onMounted(() => {
  fetchList()
  timer = setInterval(fetchList, 30000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>
