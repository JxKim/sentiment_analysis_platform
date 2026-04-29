import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/Dashboard.vue'),
    },
    {
      path: '/graph-viewer/:reportId?',
      name: 'graph-viewer',
      component: () => import('@/views/GraphViewerPage.vue'),
    },
  ],
})

export default router
