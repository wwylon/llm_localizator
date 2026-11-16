<script>
  import { t } from 'svelte-i18n';
  let error = 'Quiz not found';
</script>

{#if loading}
  <p>Loading your quizzes…</p>
{:else}
  <button class="px-4 py-2 leading-5 text-white transition-colors duration-200 transform bg-gray-700">Save changes</button>
  <h2>Home</h2>
  <p>Welcome back, {user.name}!</p>
  <img alt="Profile picture" src="/a.png" />
  <p>{$t('common.ok')}</p>
{/if}

<svg viewBox="0 0 24 24"><path d="M11.576 1.424a.6.6 0 01.848 0l10.152 10.152"/></svg>

<style>
  .box { background-color: {color}; width: 100%; }
</style>
