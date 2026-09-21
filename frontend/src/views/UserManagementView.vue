<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  departments as departmentsApi,
  roles as rolesApi,
  users as usersApi,
} from '../api/client'
import { currentUserId } from '../session'

// M1-07. The account table, administrator-only — the route carries
// `MODULE_ROLES.users` and the service answers 403 for everyone else, so the
// screen never has to decide who may be here.
//
// The botched-account problem this screen exists for is `status`: disabling an
// account refuses the tokens it already holds, from its next request onwards. The
// service has enforced that since the first day (`app.auth.current_user` reads the
// live row rather than the `title` claim), but until now the only way to reach it
// was a direct database write.

const PAGE_SIZE = 20

const rows = ref([])
const roles = ref([])
const departments = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadError = ref('')

// `''` is "no condition" for both selects, and a real option value rather than a
// cleared one: `clearable` sets the model to `undefined`, which `users.list` would
// then send as `title=undefined`.
const filters = reactive({ q: '', title: '', department: '', status: '' })

const dialogOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const editingId = ref(null)
// What the row said when the dialog opened. The save compares against this and
// sends only the fields that actually moved, so the audit entry names the change
// rather than the whole form.
const original = ref(null)
const form = reactive({
  username: '',
  password: '',
  name: '',
  email: '',
  title: '',
  department: '',
  status: 'active',
})

const isEditing = computed(() => editingId.value !== null)

// The role codes are the dictionary's, not a copy typed here: `GET /api/roles` is
// the endpoint that exists so a screen does not hardcode them (PatientListView
// says the same thing about departments).
const roleLabels = computed(() =>
  Object.fromEntries(roles.value.map((role) => [role.code, role.label])),
)

function titleLabel(code) {
  return roleLabels.value[code] ?? code
}

const hasFilters = computed(
  () => filters.q.trim() !== '' || filters.title !== '' || filters.department !== '' || filters.status !== '',
)

function stamp(value) {
  if (!value) return ''
  const at = new Date(value)
  if (Number.isNaN(at.getTime())) return value
  const pad = (number) => String(number).padStart(2, '0')
  return (
    `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}` +
    ` ${pad(at.getHours())}:${pad(at.getMinutes())}`
  )
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const result = await usersApi.list({
      q: filters.q.trim(),
      title: filters.title,
      department: filters.department,
      status: filters.status,
      page: page.value,
      size: PAGE_SIZE,
    })
    rows.value = result.items
    // `total` counts every account matching the filter, not the rows on this page.
    total.value = result.total
  } catch (error) {
    loadError.value = error.message
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function search() {
  // Back to the first page on every new search: staying on page 3 of a result set
  // that now has one row is how a search looks broken.
  page.value = 1
  load()
}

function clearFilters() {
  filters.q = ''
  filters.title = ''
  filters.department = ''
  filters.status = ''
  search()
}

function changePage(next) {
  page.value = next
  load()
}

function openCreate() {
  editingId.value = null
  original.value = null
  form.username = ''
  form.password = ''
  form.name = ''
  form.email = ''
  form.title = roles.value[0]?.code ?? ''
  form.department = departments.value[0]?.name ?? ''
  form.status = 'active'
  formError.value = ''
  dialogOpen.value = true
}

function openEdit(row) {
  editingId.value = row.id
  original.value = {
    name: row.name,
    title: row.title,
    department: row.department,
    status: row.status,
  }
  form.username = row.username
  form.password = ''
  form.name = row.name
  form.email = row.email
  form.title = row.title
  form.department = row.department
  form.status = row.status
  formError.value = ''
  dialogOpen.value = true
}

function checkPassword() {
  if (form.password.length < 8) return 'The password needs at least 8 characters.'
  // bcrypt refuses anything past 72 bytes rather than truncating it, and the
  // service answers that with a 422. Saying so here is a courtesy; the service is
  // still the one that decides.
  if (new TextEncoder().encode(form.password).length > 72) {
    return 'That password is too long — 72 bytes at most.'
  }
  return ''
}

async function save() {
  formError.value = ''
  if (!form.name.trim()) {
    formError.value = 'Enter the display name.'
    return
  }
  if (!form.title || !form.department) {
    formError.value = 'Choose a role and a department.'
    return
  }

  if (!isEditing.value) {
    if (!form.username.trim()) {
      formError.value = 'Enter the username.'
      return
    }
    if (!form.email.trim()) {
      formError.value = 'Enter the email address.'
      return
    }
    const passwordProblem = checkPassword()
    if (passwordProblem) {
      formError.value = passwordProblem
      return
    }
  }

  saving.value = true
  try {
    if (isEditing.value) {
      const payload = {}
      if (form.name.trim() !== original.value.name) payload.name = form.name.trim()
      if (form.title !== original.value.title) payload.title = form.title
      if (form.department !== original.value.department) payload.department = form.department
      if (form.status !== original.value.status) payload.status = form.status
      if (!Object.keys(payload).length) {
        dialogOpen.value = false
        ElMessage.info('Nothing changed.')
        return
      }
      await usersApi.update(editingId.value, payload)
    } else {
      await usersApi.create({
        username: form.username.trim(),
        password: form.password,
        name: form.name.trim(),
        email: form.email.trim(),
        title: form.title,
        department: form.department,
      })
    }
    dialogOpen.value = false
    await load()
    ElMessage.success(isEditing.value ? 'Account updated.' : 'Account created.')
  } catch (error) {
    // A duplicate username or email is a 409, an unregistered department a 422 —
    // both are written for the reader and belong on the form that asked.
    formError.value = error.message
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row) {
  const next = row.status === 'active' ? 'disabled' : 'active'
  if (next === 'disabled') {
    try {
      await ElMessageBox.confirm(
        `Disable ${row.name}? Any token this account already holds stops working on its next request — no need for them to sign out.`,
        'Disable account',
        { confirmButtonText: 'Disable', cancelButtonText: 'Cancel', type: 'warning' },
      )
    } catch {
      return // dismissed
    }
  }

  try {
    await usersApi.update(row.id, { status: next })
    await load()
    ElMessage.success(row.status === 'pending' ? 'Account activated.' : next === 'active' ? 'Account enabled.' : 'Account disabled.')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(async () => {
  // Both option lists come from the service, so the form offers what the service
  // will actually accept. A missing list leaves the selects empty rather than
  // offering an invented option; the dialog refuses to save without one.
  try {
    roles.value = await rolesApi.list()
  } catch {
    // load() reports the failure; the table still renders.
  }
  try {
    departments.value = await departmentsApi.list()
  } catch {
    // Same.
  }
  await load()
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-heading">User Management</h2>
        <p class="page-sub">
          <span class="data">{{ total }}</span> accounts
        </p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">New account</el-button>
    </header>

    <section class="panel">
      <div class="toolbar filters">
        <el-select
          v-model="filters.title"
          class="filter-role"
          placeholder="Any role"
          :disabled="loading"
          @change="search"
        >
          <el-option label="Any role" value="" />
          <el-option
            v-for="role in roles"
            :key="role.code"
            :label="role.label"
            :value="role.code"
          />
        </el-select>

        <el-select
          v-model="filters.department"
          class="filter-department"
          placeholder="Any department"
          :disabled="loading"
          @change="search"
        >
          <el-option label="Any department" value="" />
          <el-option
            v-for="department in departments"
            :key="department.id"
            :label="department.name"
            :value="department.name"
          />
        </el-select>

        <el-select
          v-model="filters.status"
          class="filter-status"
          placeholder="Any status"
          :disabled="loading"
          @change="search"
        >
          <el-option label="Any status" value="" />
          <el-option label="Pending" value="pending" />
          <el-option label="Active" value="active" />
          <el-option label="Disabled" value="disabled" />
        </el-select>

        <div class="search">
          <el-input
            v-model="filters.q"
            placeholder="Name or username"
            clearable
            :disabled="loading"
            @keyup.enter="search"
            @clear="search"
          />
          <el-button :icon="Refresh" :loading="loading" @click="search">Search</el-button>
        </div>

        <el-button v-if="hasFilters" link @click="clearFilters">Clear filters</el-button>
      </div>

      <div v-if="loadError" class="load-error">
        <div>
          <p class="load-error-title">Could not load the accounts</p>
          <p class="load-error-detail">{{ loadError }}</p>
        </div>
        <el-button :icon="Refresh" :loading="loading" @click="load">Try again</el-button>
      </div>

      <el-table v-else v-loading="loading" :data="rows" class="table">
        <el-table-column label="Name" min-width="200">
          <template #default="{ row }">
            <span class="name">{{ row.name }}</span>
            <span class="username data">{{ row.username }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Role" width="170">
          <template #default="{ row }">{{ titleLabel(row.title) }}</template>
        </el-table-column>

        <el-table-column label="Department" prop="department" min-width="180" />

        <el-table-column label="Email" min-width="220">
          <template #default="{ row }">
            <span class="data">{{ row.email }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Status" width="120">
          <template #default="{ row }">
            <span class="chip" :data-severity="row.status === 'active' ? 'ok' : 'alert'">
              {{ { pending: 'Pending', active: 'Active', disabled: 'Disabled' }[row.status] ?? row.status }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="Created" width="150">
          <template #default="{ row }">
            <span class="data">{{ stamp(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column width="170" align="right">
          <template #default="{ row }">
            <el-button link @click="openEdit(row)">Edit</el-button>
            <!-- Disabling yourself would sign you out on the next request, with
                 only another administrator able to undo it. The service permits
                 it; the screen does not offer it. -->
            <el-button
              link
              :disabled="row.id === currentUserId"
              :title="row.id === currentUserId ? 'You cannot disable your own account.' : ''"
              @click="toggleStatus(row)"
            >
              {{ row.status === 'pending' ? 'Activate' : row.status === 'active' ? 'Disable' : 'Enable' }}
            </el-button>
          </template>
        </el-table-column>

        <template #empty>
          <p class="empty">
            {{
              hasFilters
                ? 'No accounts match these filters. Clear one and try again.'
                : 'No accounts yet. Create one to get started.'
            }}
          </p>
        </template>
      </el-table>

      <footer v-if="total > PAGE_SIZE" class="pager">
        <el-pagination
          layout="prev, pager, next"
          :current-page="page"
          :page-size="PAGE_SIZE"
          :total="total"
          @current-change="changePage"
        />
      </footer>
    </section>

    <el-dialog
      v-model="dialogOpen"
      :title="isEditing ? 'Edit account' : 'New account'"
      width="560px"
    >
      <p class="dialog-note">
        {{
          isEditing
            ? 'Only the fields you change are sent, so the audit entry names the change rather than the whole form. The username is fixed once the account exists.'
            : 'The new account starts active and can sign in immediately. Administrators are the only role that reaches this screen.'
        }}
      </p>

      <div class="field-row">
        <label class="field">
          <span class="field-label">Username</span>
          <el-input
            v-model="form.username"
            maxlength="100"
            :disabled="isEditing"
            placeholder="Sign-in name"
          />
        </label>

        <label class="field">
          <span class="field-label">Display name</span>
          <el-input v-model="form.name" maxlength="100" placeholder="Full name" />
        </label>
      </div>

      <label v-if="!isEditing" class="field">
        <span class="field-label">Password</span>
        <el-input
          v-model="form.password"
          type="password"
          show-password
          placeholder="At least 8 characters"
        />
      </label>

      <label class="field">
        <span class="field-label">Email</span>
        <el-input
          v-model="form.email"
          maxlength="254"
          :disabled="isEditing"
          placeholder="Used for the sign-in code"
        />
      </label>

      <div class="field-row">
        <label class="field">
          <span class="field-label">Role</span>
          <el-select v-model="form.title" class="full" placeholder="Select a role">
            <el-option
              v-for="role in roles"
              :key="role.code"
              :label="role.label"
              :value="role.code"
            />
          </el-select>
        </label>

        <label class="field">
          <span class="field-label">Department</span>
          <el-select v-model="form.department" class="full" placeholder="Select a department">
            <el-option
              v-for="department in departments"
              :key="department.id"
              :label="department.name"
              :value="department.name"
            />
          </el-select>
        </label>
      </div>

      <label v-if="isEditing" class="field">
        <span class="field-label">Status</span>
        <el-select v-model="form.status" class="full">
          <el-option v-if="original?.status === 'pending'" label="Pending" value="pending" disabled />
          <el-option label="Active" value="active" />
          <el-option label="Disabled" value="disabled" />
        </el-select>
        <span class="field-hint">
          Disabling refuses the tokens this account already holds, from its next request on.
        </span>
      </label>

      <p v-if="formError" class="form-error">{{ formError }}</p>

      <template #footer>
        <el-button :disabled="saving" @click="dialogOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" @click="save">
          {{ isEditing ? 'Save changes' : 'Create account' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* The page `.toolbar` spreads its children to both ends. This bar is a run of
   filters that pack from the left; only the search is pushed to the right. */
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: flex-start;
}

.search {
  display: flex;
  gap: 8px;
  width: min(100%, 320px);
  margin-left: auto;
}

.filter-role {
  width: 180px;
}

.filter-department {
  width: 200px;
}

.filter-status {
  width: 150px;
}

.field-row {
  display: flex;
  gap: 12px;
}

.field-row > .field {
  flex: 1 1 0;
  min-width: 0;
}

.dialog-note {
  margin: 0 0 16px;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-3);
}

.form-error {
  margin: 12px 0 0;
  font-size: 12.5px;
  color: var(--alert-dark);
}

.name {
  display: block;
  font-weight: 600;
}

.username {
  display: block;
  font-size: 12px;
  color: var(--ink-3);
}

.table {
  width: 100%;
}

/* Same block as the patient list and the audit log, which scope their own copy
   rather than share one. */
.load-error {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  margin: 0;
  background: var(--alert-soft);
}

.load-error-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--alert-dark);
}

.load-error-detail {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--ink-2);
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding: 14px 20px;
  border-top: 1px solid var(--line-2);
}
</style>
