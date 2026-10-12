/* UI-only adapters. Existing commands retain their role and business guards. */
(() => {
  'use strict';
  document.body.classList.add('reader-ui');
  const visible = node => node.isConnected && !node.hidden && node.getAttribute('aria-hidden') !== 'true' && Boolean(node.getClientRects().length);
  const focusable = node => [...node.querySelectorAll('button,a[href],input,select,textarea,[tabindex]')].filter(control => !control.disabled && control.tabIndex >= 0 && visible(control));
  let active = null, opener = null, lastFocus = null, inert = new Map(), scheduled = false;
  document.addEventListener('focusin', event => {
    if (!event.target.closest('#newModal,#reportModal,.user-modal')) lastFocus = event.target;
  });
  function restore() {
    for (const [node, value] of inert) node.inert = value;
    inert.clear();
    if (opener?.isConnected && visible(opener)) opener.focus({preventScroll:true});
    active = null; opener = null;
  }
  function refresh() {
    scheduled = false;
    const modal = [...document.querySelectorAll('#newModal,#reportModal,.user-modal.open')].filter(visible).at(-1);
    if (modal === active) return;
    if (active) restore();
    if (!modal) return;
    opener = modal.contains(document.activeElement) ? lastFocus : document.activeElement; active = modal;
    modal.setAttribute('role','dialog'); modal.setAttribute('aria-modal','true');
    const heading = modal.querySelector('h1,h2,h3');
    if (heading) { heading.id ||= 'reader-dialog-' + (modal.id || 'profile'); modal.setAttribute('aria-labelledby',heading.id); }
    // Only sibling branches are inert, so a profile dialog nested in content remains usable.
    for (let branch = modal; branch && branch !== document.body; branch = branch.parentElement) {
      for (const sibling of branch.parentElement.children) if (sibling !== branch) { inert.set(sibling,sibling.inert); sibling.inert = true; }
    }
    modal.tabIndex = -1;
    (modal.querySelector('input:not([disabled]):not([type=hidden])') || focusable(modal)[0] || modal).focus({preventScroll:true});
  }
  document.addEventListener('keydown', event => {
    if (!active || !visible(active)) return;
    if (event.key === 'Escape') {
      const close = active.querySelector('[onclick*="closeNewModal"],[onclick*="closeReport"],[data-close-profile]');
      if (close) { event.preventDefault(); event.stopPropagation(); close.click(); }
    }
    if (event.key === 'Tab') {
      const controls = focusable(active), first = controls[0], last = controls.at(-1);
      if (!first) { event.preventDefault(); active.focus(); }
      else if (event.shiftKey && (document.activeElement === first || !active.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !active.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    }
  }, true);
  new MutationObserver(() => {
    if (!scheduled) { scheduled = true; requestAnimationFrame(refresh); }
  }).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden','class','aria-hidden']});
  refresh();
})();
