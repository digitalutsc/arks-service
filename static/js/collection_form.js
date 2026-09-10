// Shows the chosen noid template's description and capacity under the
// dropdown. Both come from data-* attributes on the <option>s, rendered from
// minting.noid.TEMPLATE_CATALOGUE, so the list exists in one place only.
document.addEventListener("DOMContentLoaded", function () {
  var select = document.getElementById("template");
  var help = document.getElementById("template-help");
  if (!select || !help) return;

  function show() {
    var option = select.options[select.selectedIndex];
    help.textContent = option && option.dataset.description
      ? "Template definition: " + option.dataset.description +
        " Capacity: " + option.dataset.capacity + "."
      : "";
  }

  select.addEventListener("change", show);
  show(); // a value survives a failed submit; describe it on load too
});
