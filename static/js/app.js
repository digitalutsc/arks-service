// Shell behaviour. Three handlers, all delegated from the document so they keep
// working on markup htmx swaps in (the ARK table and the job status re-render
// themselves). The CSP is `script-src 'self'`, so nothing here can live in an
// inline attribute — `onsubmit="return confirm(...)"` is silently dropped by
// the browser, which is why confirmation is wired up as data-confirm.
(function () {
  "use strict";

  // Narrow screens collapse the sidebar to a top bar with a toggle.
  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-nav-toggle]");
    if (!toggle) return;
    var sidebar = document.querySelector(".sidebar");
    if (!sidebar) return;
    var open = sidebar.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  });

  // Copy an ARK's public URL. The label flips to "Copied" so the click is
  // visibly acknowledged — a silent copy leaves people clicking twice.
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    event.preventDefault();
    var text = button.getAttribute("data-copy");

    function done() {
      var was = button.textContent;
      button.textContent = "Copied";
      button.classList.add("done");
      window.setTimeout(function () {
        button.textContent = was;
        button.classList.remove("done");
      }, 1500);
    }

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function () {
        window.prompt("Copy this URL:", text);
      });
    } else {
      // http://localhost is a secure context, but a bare IP over http is not.
      window.prompt("Copy this URL:", text);
    }
  });

  // Destructive forms confirm first.
  document.addEventListener("submit", function (event) {
    var form = event.target.closest("form[data-confirm]");
    if (!form) return;
    if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
  });
})();
