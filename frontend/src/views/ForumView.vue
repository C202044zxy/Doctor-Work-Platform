<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { forum } from '../api/client'

const categories = ['General discussion', 'Clinical practice', 'Patient communication', 'Research & learning']
const category = ref('')
const query = ref('')
const posts = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')
const selected = ref(null)
const replies = ref([])
const replyTotal = ref(0)
const replyPage = ref(1)
const detailLoading = ref(false)
const detailError = ref('')
const replyBody = ref('')
const saving = ref(false)
const composing = ref(false)
const draft = reactive({ title: '', category: 'General discussion', body: '' })
let listVersion = 0
let detailVersion = 0
const date = value => new Date(value).toLocaleString('en', { dateStyle: 'medium', timeStyle: 'short' })

async function load(reset = false) {
  if (reset) page.value = 1
  const version = ++listVersion
  loading.value = true
  error.value = ''
  try {
    const params = { page: page.value, size: 10, q: query.value.trim() }
    if (category.value) params.category = category.value
    const data = await forum.list(params)
    if (version !== listVersion) return
    posts.value = data.items
    total.value = data.total
  } catch (e) {
    if (version === listVersion) error.value = e.status === 404 ? 'The medical forum is currently disabled.' : 'Unable to load discussions. Please try again.'
  } finally {
    if (version === listVersion) loading.value = false
  }
}

async function open(post, reset = true) {
  const version = ++detailVersion
  selected.value = post
  if (reset) {
    replyPage.value = 1
    replyBody.value = ''
    replies.value = []
  }
  detailLoading.value = true
  detailError.value = ''
  try {
    const [discussion, data] = await Promise.all([forum.get(post.id), forum.replies(post.id, replyPage.value)])
    if (version !== detailVersion) return
    selected.value = discussion
    replies.value = data.items
    replyTotal.value = data.total
  } catch {
    if (version === detailVersion) detailError.value = 'Unable to load this discussion. Please try again.'
  } finally {
    if (version === detailVersion) detailLoading.value = false
  }
}

function close() {
  detailVersion++
  selected.value = null
}

async function publish() {
  if (!draft.title.trim() || !draft.body.trim() || saving.value) return
  saving.value = true
  try {
    const post = await forum.create({ ...draft })
    composing.value = false
    draft.title = ''
    draft.body = ''
    query.value = ''
    category.value = ''
    await load(true)
    await open(post)
    ElMessage.success('Discussion published')
  } catch { ElMessage.error('Unable to publish. Your draft has been kept; please try again.') }
  finally { saving.value = false }
}

async function sendReply() {
  if (!replyBody.value.trim() || saving.value) return
  saving.value = true
  const post = selected.value
  try {
    await forum.reply(post.id, replyBody.value)
    replyBody.value = ''
    replyPage.value = Math.ceil((replyTotal.value + 1) / 20)
    await open(post, false)
    await load()
    ElMessage.success('Reply posted')
  } catch { ElMessage.error('Unable to post your reply. Please try again.') }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <section class="forum-page">
    <header class="forum-hero">
      <div><p class="eyebrow">THE COLLEAGUE CONNECTION</p><h2>Share knowledge. Start a conversation.</h2><p>Exchange perspectives on clinical practice, patient communication, and lifelong learning.</p></div>
      <el-button type="primary" size="large" @click="composing = true">+ New discussion</el-button>
    </header>
    <div class="forum-layout">
      <aside class="forum-aside">
        <h3>Explore topics</h3>
        <button :class="{ active: !category }" @click="category = ''; load(true)">All discussions</button>
        <button v-for="topic in categories" :key="topic" :class="{ active: category === topic }" @click="category = topic; load(true)">{{ topic }}</button>
        <div class="guidelines"><h3>A thoughtful space</h3><p>Keep discussions respectful and remove all patient identifiers before posting.</p><p>For professional education and discussion. Posts are not individualized medical advice.</p><p>Starter posts marked “Sample” are fictional examples.</p></div>
      </aside>
      <main class="discussion-feed">
        <form class="forum-search" @submit.prevent="load(true)">
          <el-input v-model="query" aria-label="Search discussions" placeholder="Search discussions…" maxlength="200" clearable @clear="load(true)" />
          <el-button native-type="submit">Search</el-button>
        </form>
        <div class="feed-heading"><h3>{{ category || 'All discussions' }}</h3><span>{{ total }} {{ total === 1 ? 'discussion' : 'discussions' }}</span></div>
        <div v-if="error" role="alert" class="forum-state"><p>{{ error }}</p><el-button @click="load()">Retry</el-button></div>
        <div v-else-if="loading" class="forum-state" role="status">Loading discussions…</div>
        <template v-else>
          <el-empty v-if="!posts.length" description="No discussions found. Start a conversation or try another search." />
          <article v-for="post in posts" :key="post.id" class="discussion-card">
            <div class="post-tags"><el-tag effect="plain" size="small">{{ post.category }}</el-tag><el-tag v-if="post.is_sample" type="info" size="small">Sample</el-tag></div>
            <h3><button @click="open(post)">{{ post.title }}</button></h3>
            <p class="excerpt">{{ post.body }}</p>
            <footer><span class="author-avatar" aria-hidden="true">{{ post.author.slice(0, 1) }}</span><span>{{ post.author }}<small>{{ date(post.created_at) }}</small></span><button class="reply-link" @click="open(post)">{{ post.reply_count }} {{ post.reply_count === 1 ? 'reply' : 'replies' }} →</button></footer>
          </article>
          <el-pagination v-if="total > 10" v-model:current-page="page" :page-size="10" :total="total" layout="prev, pager, next" @current-change="load()" />
        </template>
      </main>
    </div>
    <el-dialog v-model="composing" title="Start a discussion" width="min(640px, 94vw)" :close-on-click-modal="false" :before-close="done => { if (!saving) done() }">
      <el-form label-position="top" @submit.prevent="publish">
        <el-form-item label="Topic"><el-select v-model="draft.category" aria-label="Topic"><el-option v-for="topic in categories" :key="topic" :label="topic" :value="topic" /></el-select></el-form-item>
        <el-form-item label="Title"><el-input v-model="draft.title" aria-label="Title" maxlength="160" show-word-limit placeholder="What would you like to discuss?" /></el-form-item>
        <el-form-item label="Your discussion"><el-input v-model="draft.body" aria-label="Your discussion" type="textarea" :rows="7" maxlength="10000" show-word-limit placeholder="Share a question or perspective. Do not include patient identifiers." /></el-form-item>
        <el-button type="primary" native-type="submit" :loading="saving" :disabled="!draft.title.trim() || !draft.body.trim()">Publish discussion</el-button>
      </el-form>
    </el-dialog>
    <el-dialog :model-value="!!selected" title="Discussion" width="min(760px, 94vw)" :close-on-click-modal="false" :before-close="done => { if (!saving) { close(); done() } }" @update:model-value="value => { if (!value) close() }">
      <template v-if="selected">
        <el-tag>{{ selected.category }}</el-tag> <el-tag v-if="selected.is_sample" type="info">Sample</el-tag>
        <h2>{{ selected.title }}</h2><p class="post-meta">{{ selected.author }} · {{ date(selected.created_at) }}</p>
        <p class="post-body">{{ selected.body }}</p>
        <p v-if="detailLoading" role="status">Loading replies…</p>
        <div v-else-if="detailError" role="alert"><p>{{ detailError }}</p><el-button @click="open(selected, false)">Retry</el-button></div>
        <template v-else>
          <h3>{{ replyTotal }} {{ replyTotal === 1 ? 'reply' : 'replies' }}</h3>
          <p v-if="!replies.length">Be the first to join the conversation.</p>
          <article v-for="reply in replies" :key="reply.id" class="forum-reply"><strong>{{ reply.author }}</strong> <el-tag v-if="reply.is_sample" type="info" size="small">Sample</el-tag><small>{{ date(reply.created_at) }}</small><p class="post-body">{{ reply.body }}</p></article>
          <el-pagination v-if="replyTotal > 20" v-model:current-page="replyPage" :page-size="20" :total="replyTotal" layout="prev, pager, next" @current-change="open(selected, false)" />
          <form class="reply-form" @submit.prevent="sendReply"><label for="forum-reply">Join the conversation</label><el-input id="forum-reply" v-model="replyBody" type="textarea" :rows="3" maxlength="5000" show-word-limit placeholder="Write a respectful reply without patient identifiers…" /><el-button native-type="submit" type="primary" :loading="saving" :disabled="!replyBody.trim()">Post reply</el-button></form>
        </template>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.forum-page { max-width: 1220px; margin: 0 auto; padding: 24px; color: #223c40; }
.forum-hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; background: #e9f4f0; border: 1px solid #d6e9e1; border-radius: 16px; padding: 32px; margin-bottom: 28px; }
.eyebrow { font-size: 11px; font-weight: 700; letter-spacing: 2px; color: #267568; }
h2 { font-size: 26px; line-height: 1.3; margin: 12px 0; }
.forum-hero p:last-child { color: #55716d; line-height: 1.6; max-width: 620px; }
.forum-layout { display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 30px; }
h3 { font-size: 16px; }
.forum-aside > button { display: block; width: 100%; text-align: left; border: 0; padding: 14px; margin: 4px 0; border-radius: 8px; background: transparent; color: #546766; cursor: pointer; font: inherit; font-size: 13px; }
.forum-aside > button.active { background: #e5f1ed; color: #146555; font-weight: 600; }
.guidelines { border-top: 1px solid #dfe7e4; margin-top: 25px; padding: 12px; font-size: 12px; line-height: 1.8; color: #697b79; }
.forum-search { display: flex; gap: 10px; }
.feed-heading { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; }
.feed-heading span, .post-meta { font-size: 12px; color: #71837f; }
.discussion-card { border: 1px solid #e0e8e5; border-radius: 12px; padding: 22px; margin-bottom: 14px; background: white; }
.post-tags { display: flex; gap: 8px; }
.discussion-card h3 button { font: inherit; font-size: 18px; color: #254540; background: none; border: none; padding: 0; cursor: pointer; text-align: left; }
.discussion-card h3 button:hover { color: #16846f; }
.excerpt { color: #6b7c78; line-height: 1.65; font-size: 13px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; }
footer { display: flex; align-items: center; gap: 10px; font-size: 12px; margin-top: 20px; }
small { display: block; color: #86938f; font-size: 11px; margin-top: 4px; }
.author-avatar { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; background: #edf2e9; color: #547151; }
.reply-link { margin-left: auto; border: 0; background: none; color: #42796b; cursor: pointer; }
.forum-state { text-align: center; padding: 48px 20px; }
.post-body { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
.forum-reply { border-top: 1px solid #e5ebe8; padding: 20px 0 6px; }
.reply-form { display: grid; gap: 14px; margin-top: 24px; }
.reply-form .el-button { justify-self: end; }
@media (max-width: 800px) { .forum-page { padding: 12px; } .forum-layout { grid-template-columns: 1fr; } .forum-hero { align-items: flex-start; flex-direction: column; padding: 24px; } .guidelines { margin-top: 12px; } }
</style>
