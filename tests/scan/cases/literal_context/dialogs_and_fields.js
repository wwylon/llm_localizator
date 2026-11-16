const OPTIONS = [
  { id: 'alone', label: 'Going alone', desc: 'The maker may play without a partner.' },
];
function stop(n) {
  if (!confirm('Stop all running tasks?')) return;
  showToast(n ? 'API token saved' : 'API token cleared');
  dialog('New research thread', body, 'Create');
}
