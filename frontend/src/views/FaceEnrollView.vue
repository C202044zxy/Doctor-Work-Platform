<script setup>
// T42 §4.3.3【录入】. The counterpart to the sign-in page's face panel: that one
// verifies against a stored reference image, this one stores it.
//
// The thumbnail at the end is not decoration. It renders through
// GET /api/auth/face/image/{ref} rather than from the blob we just captured,
// which is the only way to see from the browser that the controlled-read path
// works — the file is deliberately absent from every static mount, so a picture
// that appears here can only have come through the authorised route (§4.3.1 ③).
import { computed, onUnmounted, ref } from 'vue'

import { authentication, faceImageUrl } from '../api/client'
import { currentUsername } from '../session'
import CameraCapture from '../components/CameraCapture.vue'
import MockBadge from '../components/MockBadge.vue'

const photo = ref(null)
const busy = ref(false)
const error = ref('')
const enrolled = ref(null)
const thumbnail = ref('')
const capture = ref(null)

const enrolledOn = computed(() => {
  if (!enrolled.value?.enrolled_at) return ''
  const at = new Date(enrolled.value.enrolled_at)
  return Number.isNaN(at.getTime()) ? enrolled.value.enrolled_at : at.toLocaleString()
})

// Object URLs pin the decoded image in memory until they are revoked, and this
// page can be re-enrolled any number of times without a reload.
onUnmounted(() => {
  if (thumbnail.value) URL.revokeObjectURL(thumbnail.value)
})

function handleCaptured(blob) {
  photo.value = blob
  error.value = ''
}

async function enroll() {
  error.value = ''
  if (!photo.value) {
    error.value = 'Take a photo first.'
    return
  }
  busy.value = true
  try {
    const data = await authentication.faceEnroll(photo.value, currentUsername.value)
    enrolled.value = data
    if (thumbnail.value) URL.revokeObjectURL(thumbnail.value)
    thumbnail.value = await faceImageUrl(data.face_image_ref, currentUsername.value)
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
}

function again() {
  enrolled.value = null
  photo.value = null
  if (thumbnail.value) URL.revokeObjectURL(thumbnail.value)
  thumbnail.value = ''
  error.value = ''
  capture.value?.reset()
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-heading">Face enrolment</h2>
        <p class="page-sub">Store the reference photo that face sign-in compares against.</p>
      </div>
      <MockBadge />
    </header>

    <section class="panel">
      <div class="panel-head">
        <h3>Reference photo</h3>
      </div>

      <div class="panel-body enrol">
        <template v-if="!enrolled">
          <p class="lede">
            Signing in with your face compares a live photo against the one stored here. Enrolling
            again simply replaces it — there is no approval step in between.
          </p>
          <CameraCapture ref="capture" purpose="enrol" :busy="busy" @captured="handleCaptured" />
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <el-button
            v-if="photo"
            type="primary"
            class="submit"
            :loading="busy"
            :disabled="busy"
            @click="enroll"
          >
            Save this photo
          </el-button>
        </template>

        <template v-else>
          <p class="lede">
            Saved. This is the stored image, read back through the authorised endpoint.
          </p>
          <img v-if="thumbnail" :src="thumbnail" class="thumb" alt="Stored reference photo" />
          <dl class="facts">
            <div>
              <dt>Reference</dt>
              <dd class="data">{{ enrolled.face_image_ref }}</dd>
            </div>
            <div>
              <dt>Enrolled</dt>
              <dd>{{ enrolledOn }}</dd>
            </div>
          </dl>
          <el-button @click="again">Enrol again</el-button>
        </template>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h3>What is simulated</h3>
      </div>
      <div class="panel-body">
        <ul class="notes">
          <li>
            There is no liveness detection. The frame check on the camera preview is a framing
            guide for the operator, not a defence against a photograph of a photograph.
          </li>
          <li>
            Matching is a perceptual hash comparison, not a face-recognition model. The
            comparison itself runs for real; only the provider that would do it in production
            is substituted.
          </li>
          <li>
            The image is written to a directory that is not served statically. Reaching it needs
            a token and the reference above, which is what the thumbnail is proving.
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>

<style scoped>
.enrol {
  max-width: 460px;
}

.lede {
  margin: 0 0 18px;
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--ink-2);
}

.thumb {
  display: block;
  width: 100%;
  max-width: 320px;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.facts {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 32px;
  margin: 18px 0;
}

.facts dt {
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-3);
}

.facts dd {
  margin: 0;
  font-size: 13px;
}

.notes {
  padding-left: 18px;
  margin: 0;
  font-size: 13px;
  line-height: 1.65;
  color: var(--ink-2);
}

.notes li + li {
  margin-top: 10px;
}

.form-error {
  padding: 10px 12px;
  margin: 14px 0 0;
  font-size: 13px;
  color: var(--alert-dark);
  background: var(--alert-soft);
  border-radius: var(--radius);
}

.submit {
  width: 100%;
  max-width: 320px;
  margin-top: 14px;
}
</style>
