<script setup>
import { onUnmounted, ref, watch } from 'vue'
import { imageBlob } from '../api/work'
const props = defineProps({ url: String })
const source = ref(''), error = ref('')
let generation = 0
watch(() => props.url, async (url) => {
  const version = ++generation
  if (source.value) URL.revokeObjectURL(source.value)
  source.value = ''; error.value = ''
  try {
    const blob = await imageBlob(url)
    if (version === generation) source.value = blob
    else URL.revokeObjectURL(blob)
  } catch (err) { if (version === generation) error.value = err.message }
}, { immediate: true })
onUnmounted(() => { generation++; if (source.value) URL.revokeObjectURL(source.value) })
</script>
<template>
  <a v-if="source" :href="source" target="_blank" rel="noopener"><img :src="source" alt="Consultation attachment — open full image" style="max-width:240px;max-height:240px;border-radius:8px" /></a>
  <span v-else>{{ error || 'Loading image…' }}</span>
</template>
