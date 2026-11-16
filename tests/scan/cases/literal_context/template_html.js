function render(el, n, total) {
  el.innerHTML = `<div class="pager" title="Filter title…">${n} of ${total}
    <b>Loading results</b><rect x="${n}" rx="2" fill="${total}"></rect></div>`;
  status.textContent = `Bots thinking… ${n} s`;
}
