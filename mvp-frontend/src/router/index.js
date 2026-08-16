import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', public: true }
  },
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: 'Dashboard' }
  },
  {
    path: '/hosts',
    name: 'HostManage',
    component: () => import('@/views/HostManage.vue'),
    meta: { title: '主机管理' }
  },
  {
    path: '/deploy',
    name: 'DeployWizard',
    component: () => import('@/views/DeployWizard.vue'),
    meta: { title: '部署向导' }
  },
  {
    path: '/history',
    name: 'DeployHistory',
    component: () => import('@/views/DeployHistory.vue'),
    meta: { title: '部署历史' }
  },
  {
    path: '/config',
    name: 'SystemConfig',
    component: () => import('@/views/SystemConfig.vue'),
    meta: { title: '系统配置' }
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    redirect: '/'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 全局前置守卫：未登录重定向到 /login
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.public) {
    // 已登录访问登录页，跳转首页
    if (token && to.path === '/login') {
      next('/')
    } else {
      next()
    }
  } else {
    if (!token) {
      next({ path: '/login', query: { redirect: to.fullPath } })
    } else {
      next()
    }
  }
})

router.afterEach((to) => {
  const base = 'MVP AI部署助手'
  document.title = to.meta.title ? `${to.meta.title} - ${base}` : base
})

export default router
