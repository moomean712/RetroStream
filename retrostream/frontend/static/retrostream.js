(function () {
  function copyUrl(button) {
    var field = document.getElementById(button.getAttribute("data-target"));
    if (!field) { return false; }
    field.focus();
    field.select();
    if (window.clipboardData && window.clipboardData.setData) {
      window.clipboardData.setData("Text", field.value);
      button.innerHTML = "Copied";
    } else if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(field.value).then(function () { button.innerHTML = "Copied"; });
    } else {
      try { if (document.execCommand("copy")) { button.innerHTML = "Copied"; } } catch (ignore) {}
    }
    return false;
  }
  function ready() {
    var buttons = document.getElementsByTagName("button");
    var i, selectPage;
    for (i = 0; i < buttons.length; i += 1) {
      if ((" " + buttons[i].className + " ").indexOf(" copy-url ") !== -1) {
        buttons[i].onclick = function () { return copyUrl(this); };
      }
    }
    selectPage = document.getElementById("select-page");
    if (selectPage) {
      selectPage.onclick = function () {
        var inputs = document.getElementsByTagName("input"), checked = false;
        for (i = 0; i < inputs.length; i += 1) {
          if ((" " + inputs[i].className + " ").indexOf(" media-check ") !== -1 && !inputs[i].checked) {
            checked = true;
          }
        }
        for (i = 0; i < inputs.length; i += 1) {
          if ((" " + inputs[i].className + " ").indexOf(" media-check ") !== -1) {
            inputs[i].checked = checked;
          }
        }
        this.innerHTML = checked ? "Clear selection" : "Select page";
        return false;
      };
    }
  }
  if (window.addEventListener) { window.addEventListener("load", ready, false); }
  else if (window.attachEvent) { window.attachEvent("onload", ready); }
}());
