<script setup>
import { onMounted, ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { emr } from '../api/client.js'
import { currentTitle } from '../session.js'
const canReview = computed(() => currentTitle.value === 'senior')
const route = useRoute()
const queue = ref(route.name === 'review')
watch(() => route.name, () => { queue.value = route.name === 'review'; page.value = 1; load() })
const data = ref({ items: [], total: 0 })
const page = ref(1)
const busy = ref(false)
const error = ref('')
const comments = ref({})
async function load() {
  busy.value = true
  error.value = ''
  try { data.value = await emr.get(`/emr/${queue.value ? 'reviews' : 'my-submissions'}?page=${page.value}&size=10`) }
  catch { error.value = 'Unable to load records. Please retry.' }
  finally { busy.value = false }
}
async function review(row, action) {
  const comment = comments.value[row.id] || ''
  if (action === 'reject' && !comment.trim()) { error.value = 'A rejection comment is required.'; return }
  busy.value = true
  try { await emr.post(`/emr/records/${row.id}/review`, { action, comment }); await load() }
  catch { error.value = 'Review failed. Refresh the list and retry.' }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <section class="review-workspace"><h1>{{ queue ? 'Pending review' : 'My submissions' }}</h1>
    <button :disabled="busy" @click="queue = false; page = 1; load()">My submissions</button>
    <button v-if="canReview" :disabled="busy" @click="queue = true; page = 1; load()">Pending review</button>
    <button :disabled="busy" @click="load">Refresh</button>
    <p v-if="busy" role="status">Loading…</p><p v-if="error" role="alert">{{ error }}</p>
    <p v-if="!busy && !data.items.length">No records to display.</p>
    <article v-for="r in data.items" :key="r.id"><h2>{{ r.patient_name }} · {{ r.template_name }}</h2><p>{{ r.status }} · Version {{ r.version }} · {{ r.author_name }}</p><p v-if="r.review_comment">Review comment: {{ r.review_comment }}</p><router-link :to="{ path: '/records', query: { record: r.id } }">Read record and orders</router-link><template v-if="queue && canReview"><label>Review comment<textarea v-model="comments[r.id]" /></label><button :disabled="busy" @click="review(r, 'approve')">Approve and archive</button><button :disabled="busy" @click="review(r, 'reject')">Reject with comment</button></template></article>
    <button :disabled="busy || page <= 1" @click="page--; load()">Previous</button><span>Page {{ page }} · {{ data.total }} records</span><button :disabled="busy || page * 10 >= data.total" @click="page++; load()">Next</button>
  </section>
</template>
<style scoped>
.review-workspace { padding: 24px; } article { padding: 20px; margin: 16px 0; background: white; border: 1px solid #d5dde4; border-radius: 8px; } button, textarea { padding: 10px; margin: 8px; } label { display: flex; flex-direction: column; } pre { white-space: pre-wrap; } [role=alert] { color: #a4161a; }
</style>
