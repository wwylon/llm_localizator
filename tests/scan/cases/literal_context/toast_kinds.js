function save(ok) {
  showToast('Settings saved', 'info');
  showToast('Could not reach the server', 'err');
  toast('Queue paused', 'warn');
  showToast(ok ? 'Done' : 'Failed to save the file', 'error');
}
