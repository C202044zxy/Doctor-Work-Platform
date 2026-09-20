<script setup>
// T42 §4.4. Four states, in the order the user walks them:
//   idle → streaming → captured → (enrol or verify, or back to streaming)
// `error` is reachable from any of them and always offers a retry.
//
// The component owns the camera and the frame; it does not know what the photo is
// for. The parent decides, which keeps the same component usable for enrolling a
// reference image and for verifying against one.
import { nextTick, onUnmounted, ref, useTemplateRef } from 'vue'

import { captureBlob, openCamera, stopCamera } from '../face-camera'

defineProps({
  // `enrol` and `verify` differ only in their wording; the mechanics are the same.
  purpose: { type: String, default: 'verify' },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['captured'])

const state = ref('idle')
const error = ref('')
const preview = ref('')
const video = useTemplateRef('video')
let stream = null
let disposed = false

// §4.4: a stream left running keeps the camera light on, which is the single most
// visible way this page can look broken during a demo.
onUnmounted(() => {
  disposed = true
  release()
})

function release() {
  stopCamera(stream)
  stream = null
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''
}

async function start() {
  error.value = ''
  try {
    const opened = await openCamera()
    if (disposed) {
      stopCamera(opened)
      return
    }
    stream = opened
    state.value = 'streaming'
    await nextTick()
    video.value.srcObject = opened
    await video.value.play()
  } catch (err) {
    state.value = 'error'
    error.value = err.message
  }
}

async function shoot() {
  error.value = ''
  try {
    const blob = await captureBlob(video.value)
    // Freeze the frame for review, and let go of the camera while the user decides.
    release()
    preview.value = URL.createObjectURL(blob)
    state.value = 'captured'
    emit('captured', blob)
  } catch (err) {
    state.value = 'error'
    error.value = err.message
  }
}

function retake() {
  release()
  start()
}

function reset() {
  release()
  state.value = 'idle'
  error.value = ''
}

defineExpose({ reset })
</script>

<template>
  <div class="capture">
    <div v-if="state === 'idle'" class="idle-actions">
      <el-button :disabled="busy" @click="start">Open the camera</el-button>
    </div>

    <template v-else-if="state === 'streaming'">
      <video ref="video" class="frame" autoplay muted playsinline aria-label="Camera preview" />
      <p class="hint">
        {{ purpose === 'enrol' ? 'Centre your face in the frame.' : 'Look at the camera.' }}
      </p>
      <div class="actions">
        <el-button type="primary" :disabled="busy" @click="shoot">Take the photo</el-button>
        <el-button :disabled="busy" @click="reset">Cancel</el-button>
      </div>
    </template>

    <template v-else-if="state === 'captured'">
      <img :src="preview" class="frame" alt="Captured photo" />
      <p class="hint">Use this photo, or take another one.</p>
      <div class="actions">
        <el-button :disabled="busy" @click="retake">Retake</el-button>
        <el-button :disabled="busy" @click="reset">Cancel</el-button>
      </div>
    </template>

    <template v-else>
      <p class="capture-error" role="alert">{{ error }}</p>
      <div class="actions">
        <el-button type="primary" @click="start">Try again</el-button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.capture {
  display: block;
}

.idle-actions {
  display: flex;
  justify-content: center;
}

.frame {
  display: block;
  width: 100%;
  max-width: 320px;
  margin-inline: auto;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  transform: scaleX(-1);
}

.hint {
  text-align: center;
  margin: 10px 0 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-2);
}

.actions {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.capture-error {
  padding: 10px 12px;
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--alert-dark);
  background: var(--alert-soft);
  border-radius: var(--radius);
}
</style>
