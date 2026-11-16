<h1>Account settings</h1>
<?php
$query = "SELECT id FROM users WHERE active = 1";
if ($count > 0) { $label = "x"; }
?>
<p>Change your password below.</p>
<script>
  document.getElementById("save").textContent = "Don't forget to save";
</script>
