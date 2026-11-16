export function onKey(e: KeyboardEvent) {
  if (e.code === 'Enter' || ['Tab', 'Space'].includes(e.key)) {
    plausible('Started Game');
    trackEvent('user interaction', 'create snippet', 'Saved Snippet');
  }
}
export const gutters = ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'];
export const hotkeys = { save: 'Ctrl + S', find: 'command + F' };
export function fail() {
  throw createError({ statusCode: 404, statusMessage: 'Entity Not Found' });
}
export const toastOk = () => toast.success('Snippet exported to your folder!');
