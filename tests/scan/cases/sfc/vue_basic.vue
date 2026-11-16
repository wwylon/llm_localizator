<template>
  <div class="px-4 py-2 flex">
    <h1>Create account</h1>
    <p>Already have an account?</p>
    <button class="btn btn-primary" @click="go">Forgot password?</button>
    <input placeholder="Your email address" :aria-label="t('email')" />
    <span>{{ count }} items selected</span>
    <span>{{ $t('ok') }}</span>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
const msg = ref('Unexpected error!')
const url = '/api/v1/items'
</script>

<style scoped>
.flex { display: flex; background-color: #fff; }
</style>
