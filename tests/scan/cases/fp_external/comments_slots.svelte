<script>
  import { _ } from 'svelte-i18n';
  export let lang;
</script>

<!-- Welcome Back to the quiz -->
<!-- <button>{$_('words.kick')}</button> -->

<p>{lang.flag} {lang.name}</p>
<p>{$_('words.answer')}</p>
<h2>Choose your answer below</h2>
