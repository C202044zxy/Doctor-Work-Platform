<script setup>
import { onUnmounted, ref, watch } from 'vue'
import { accessToken } from '../session'
import { work } from '../api/work'

const props = defineProps({ roomKey: String, callId: String, refresh: Number, test: Boolean })
const rows = ref([]), error = ref(''), loading = ref(false), mediaUrl = ref(''), selected = ref('')
let version = 0
async function load() {
  const expected = ++version
  error.value = ''
  try {
    const result = await work(props.test ? `/rooms/${props.roomKey}/test-recordings` : `/rooms/${props.roomKey}/calls/${props.callId}/recordings`)
    if (expected === version) rows.value = result
  } catch (err) { if (expected === version) error.value = err.message }
}
async function play(row) {
  const expected = version
  loading.value = true; error.value = ''
  try {
    const response = await fetch(`/api/recordings/${row.id}/media`, { headers: { Authorization: `Bearer ${accessToken()}` } })
    if (!response.ok) throw new Error('Replay is unavailable or access was denied. Refresh and try again.')
    const blob = await response.blob()
    if (expected !== version) return
    close()
    mediaUrl.value = URL.createObjectURL(blob)
    selected.value = row.owner_name
  } catch (err) { if (expected === version) error.value = err.message }
  finally { loading.value = false }
}
function close() { if (mediaUrl.value) URL.revokeObjectURL(mediaUrl.value); mediaUrl.value = '' }
watch(() => [props.roomKey, props.callId, props.refresh], () => { close(); rows.value = []; load() }, { immediate: true })
onUnmounted(() => { version++; close() })
</script>
<template>
  <div class="replay">
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="!rows.length" class="muted">{{ test ? 'No saved test recordings. The latest 100 tests appear here.' : 'No saved replay for this call.' }}</p>
    <div v-for="row in rows" :key="row.id" class="replay-row">
      <span><strong v-if="row.is_test">{{ row.filename }} · Test recording · </strong>{{ row.owner_name }} · {{ row.status === 'partial' ? 'Partial recording' : row.status === 'ready' ? 'Saved replay' : 'Recording / uploading' }} · {{ (row.byte_size / 1048576).toFixed(1) }} MB</span>
      <el-button v-if="row.playable" size="small" :loading="loading" @click="play(row)">Play replay</el-button>
    </div>
    <el-button link size="small" @click="load">Refresh replays</el-button>
    <div v-if="mediaUrl" class="player"><p>Recorded by {{ selected }} <el-button link @click="close">Close replay</el-button></p><video :src="mediaUrl" controls playsinline preload="metadata" /></div>
  </div>
</template>
<style scoped>
.replay{margin:8px 0 18px;padding:12px;border:1px solid var(--line,#dce6e3);border-radius:8px}.replay-row{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px;margin:8px 0}.muted{font-size:12px;color:#657871}.player video{width:100%;max-height:440px;background:#142b28}.player p{font-size:12px}
</style>
