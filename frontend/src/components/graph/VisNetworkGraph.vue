<template>
  <div class="vis-graph" ref="containerRef" :style="{ height }" />
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { Network, DataSet } from 'vis-network/standalone'

interface Node {
  id: string
  label: string
  group?: string
  [key: string]: any
}

interface Edge {
  from: string
  to: string
  label?: string
  [key: string]: any
}

const props = withDefaults(defineProps<{
  nodes: Node[]
  edges: Edge[]
  height?: string
  options?: Record<string, any>
}>(), {
  height: '400px',
})

const emit = defineEmits<{
  'node-click': [nodeId: string, node: Node]
  'node-deselect': []
  stabilized: []
}>()

const containerRef = ref<HTMLElement | null>(null)
let network: Network | null = null
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let nodesDataset: any = null

const defaultOptions = {
  nodes: {
    shape: 'dot',
    size: 16,
    font: { size: 12, color: '#303133' },
    borderWidth: 2,
  },
  edges: {
    width: 1,
    color: { color: '#c0c4cc', highlight: '#409eff' },
    font: { size: 10, color: '#909399' },
    arrows: { to: { enabled: true, scaleFactor: 0.5 } },
  },
  physics: {
    stabilization: { iterations: 200 },
    solver: 'forceAtlas2Based',
  },
  interaction: {
    hover: true,
    tooltipDelay: 200,
    navigationButtons: true,
    keyboard: true,
  },
}

function createNetwork() {
  if (!containerRef.value) return
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const nodes = props.nodes as any[]
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const edges = props.edges as any[]

  nodesDataset = new DataSet(nodes)
  const edgesDataset = new DataSet(edges)

  network = new Network(
    containerRef.value,
    { nodes: nodesDataset, edges: edgesDataset },
    { ...defaultOptions, ...props.options },
  )

  network.on('click', (params: any) => {
    if (params.nodes.length > 0) {
      const nodeId: string = params.nodes[0]
      const node = nodesDataset?.get(nodeId) as Node | null
      if (node) emit('node-click', nodeId, node)
    } else {
      emit('node-deselect')
    }
  })

  network.on('stabilized', () => {
    emit('stabilized')
  })
}

function fit() {
  network?.fit({ animation: true })
}

function focusNode(nodeId: string) {
  network?.focus(nodeId, { scale: 1.5, animation: true })
}

function selectNodes(ids: string[]) {
  network?.selectNodes(ids)
}

watch(() => [props.nodes, props.edges], () => {
  if (nodesDataset && network) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const nodes = props.nodes as any[]
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const edges = props.edges as any[]
    nodesDataset.update(nodes)
    const edgesDataset = new DataSet(edges)
    network.setData({ nodes: nodesDataset, edges: edgesDataset })
  }
}, { deep: true })

onMounted(() => createNetwork())

onUnmounted(() => {
  network?.destroy()
  network = null
})

defineExpose({ fit, focusNode, selectNodes, network })
</script>

<style scoped>
.vis-graph {
  width: 100%;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}
</style>
