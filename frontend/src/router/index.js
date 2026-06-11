import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue'),
    meta: { title: '总览仪表盘' }
  },
  {
    path: '/artifact/:id',
    name: 'ArtifactDetail',
    component: () => import('../views/ArtifactDetail.vue'),
    meta: { title: '器物详情' }
  },
  {
    path: '/viewer',
    name: 'Viewer',
    component: () => import('../views/Viewer3D.vue'),
    meta: { title: '3D可视化' }
  },
  {
    path: '/alerts',
    name: 'Alerts',
    component: () => import('../views/Alerts.vue'),
    meta: { title: '告警中心' }
  },
  {
    path: '/spray',
    name: 'SprayTasks',
    component: () => import('../views/SprayTasks.vue'),
    meta: { title: '缓蚀剂喷涂' }
  },
  {
    path: '/artifacts',
    name: 'Artifacts',
    component: () => import('../views/ArtifactList.vue'),
    meta: { title: '藏品管理' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  document.title = to.meta.title ? `${to.meta.title} - 青铜器预警系统` : '青铜器预警系统'
  next()
})

export default router
