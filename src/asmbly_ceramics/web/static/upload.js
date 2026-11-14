// The drop-off form's photo upload and its small conveniences (decision 0002).
// A plain script: no build step, no library, no inline script. Every check here is for
// the person's convenience only; the server checks everything again.
(function () {
  "use strict";

  document.documentElement.classList.add("js");

  var form = document.getElementById("drop-off-form");
  if (!form) { return; }
  var field = document.getElementById("photos-field");
  // The limits and sentences come from the server (domain/limits.py and web/fields.py).
  var PHOTOS_MIN = parseInt(field.getAttribute("data-photos-min"), 10);
  var PHOTOS_MAX = parseInt(field.getAttribute("data-photos-max"), 10);
  var PHOTO_MAX_BYTES = parseInt(field.getAttribute("data-photo-max-bytes"), 10);
  var AT_ONCE = 2;
  function numbered(name) {
    var text = field.getAttribute(name);
    return function (n) { return text.replace("{n}", String(n)); };
  }
  var MESSAGES = {
    count: field.getAttribute("data-message-count"),
    tooLarge: numbered("data-message-too-large"),
    failed: numbered("data-message-failed"),
    uploading: function (n, total) { return "Uploading photo " + n + " of " + total + "\u2026"; },
    expired: field.getAttribute("data-message-expired"),
    tryAgain: field.getAttribute("data-message-try-again")
  };

  var picker = document.getElementById("photos");
  var list = document.getElementById("photo-list");
  var errors = document.getElementById("photos-error");
  var status = document.getElementById("upload-status");
  var submit = document.getElementById("submit-button");
  var glaze = form.querySelector(".glaze-types");
  var pieces = document.getElementById("pieces");
  var chosen = []; // {file, url} in the person's order, not yet uploaded

  var summary = document.getElementById("error-summary");
  if (summary) { summary.focus(); }

  // The glaze fieldset: shown, and posted, only for a firing type that needs one.
  function showGlaze() {
    var picked = form.querySelector('input[name="firing_type"]:checked');
    var needs = picked !== null && picked.getAttribute("data-needs-glaze") === "true";
    if (glaze) {
      glaze.hidden = !needs;
      glaze.disabled = !needs;
    }
  }
  form.querySelectorAll('input[name="firing_type"]').forEach(function (radio) {
    radio.addEventListener("change", showGlaze);
  });
  showGlaze();

  // The pieces stepper.
  form.querySelectorAll(".step").forEach(function (button) {
    button.addEventListener("click", function () {
      var value = parseInt(pieces.value, 10);
      if (isNaN(value)) { value = 0; }
      var next = value + parseInt(button.getAttribute("data-step"), 10);
      var min = parseInt(pieces.min, 10);
      var max = parseInt(pieces.max, 10);
      pieces.value = String(Math.min(max, Math.max(min, next)));
    });
  });

  function keptCount() {
    return list.querySelectorAll(".photo-kept").length;
  }

  function showErrors(messages) {
    errors.textContent = "";
    messages.forEach(function (message) {
      var p = document.createElement("p");
      p.className = "field-error";
      p.textContent = message;
      errors.appendChild(p);
    });
  }

  function removeButton(onRemove) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "remove";
    button.textContent = "Remove";
    button.addEventListener("click", function () {
      if (busy) { return; }
      onRemove();
    });
    return button;
  }

  // While the photos upload, the list can't change: the slots were asked for these.
  var busy = false;
  function setBusy(value) {
    busy = value;
    submit.disabled = value;
    picker.disabled = value;
    list.querySelectorAll(".remove").forEach(function (button) { button.disabled = value; });
  }

  // Photos already uploaded and kept by the server after a refused submit.
  list.querySelectorAll(".photo-kept .remove").forEach(function (button) {
    button.addEventListener("click", function () {
      if (busy) { return; }
      button.parentNode.remove();
    });
  });

  // Each pick adds to the list: a phone's camera returns one photo per pick.
  picker.addEventListener("change", function () {
    if (busy) { picker.value = ""; return; }
    var files = Array.prototype.slice.call(picker.files);
    var dropped = false;
    files.forEach(function (file) {
      if (keptCount() + chosen.length >= PHOTOS_MAX) { dropped = true; return; }
      var entry = { file: file, url: URL.createObjectURL(file) };
      chosen.push(entry);
      var item = document.createElement("li");
      item.className = "photo-item";
      var img = document.createElement("img");
      img.src = entry.url;
      img.alt = "";
      var label = document.createElement("span");
      label.className = "photo-label";
      label.textContent = file.name;
      item.appendChild(img);
      item.appendChild(label);
      item.appendChild(removeButton(function () {
        chosen.splice(chosen.indexOf(entry), 1);
        URL.revokeObjectURL(entry.url);
        item.remove();
      }));
      list.appendChild(item);
    });
    showErrors(dropped ? [MESSAGES.count] : []);
    picker.value = "";
  });

  function fail(message) {
    showErrors([message]);
    status.textContent = "";
    setBusy(false);
  }

  function contentType(file) {
    // The bucket's policy needs an image/ type; the server's inspector decides what the
    // file really is, with its own message.
    return file.type && file.type.indexOf("image/") === 0 ? file.type : "image/unknown";
  }

  function upload(slot, file) {
    var data = new FormData();
    Object.keys(slot.fields).forEach(function (name) {
      data.append(name, slot.fields[name]);
    });
    data.append("Content-Type", contentType(file));
    data.append("file", file); // S3 requires the file last
    return fetch(slot.url, { method: "POST", body: data, credentials: "omit" }).then(function (answer) {
      if (!answer.ok) { throw new Error("upload refused"); }
    });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (busy) { return; }
    var total = keptCount() + chosen.length;
    if (total < PHOTOS_MIN || total > PHOTOS_MAX) {
      showErrors([MESSAGES.count]);
      return;
    }
    var tooLarge = [];
    chosen.forEach(function (entry, i) {
      if (entry.file.size > PHOTO_MAX_BYTES) { tooLarge.push(MESSAGES.tooLarge(keptCount() + i + 1)); }
    });
    if (tooLarge.length) {
      showErrors(tooLarge);
      return;
    }
    showErrors([]);
    setBusy(true);
    var sending = chosen.slice(); // the photos the slots are for, fixed now
    if (!sending.length) {
      HTMLFormElement.prototype.submit.call(form);
      return;
    }
    var token = form.querySelector('input[name="submission"]').value;
    fetch("/drop-off/uploads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ count: sending.length, submission: token })
    }).then(function (answer) {
      return answer.json().then(function (body) { return { status: answer.status, body: body }; });
    }).then(function (result) {
      if (result.status === 429 && result.body.message) { return fail(result.body.message); }
      if (result.body.error === "expired") { return fail(MESSAGES.expired); }
      if (result.status !== 200 || !result.body.slots || result.body.slots.length !== sending.length) { return fail(MESSAGES.tryAgain); }
      var slots = result.body.slots;
      var done = 0;
      var next = 0;
      var failed = false;
      var offset = keptCount();
      function work() {
        if (failed || next >= sending.length) { return Promise.resolve(); }
        var i = next;
        next += 1;
        return upload(slots[i], sending[i].file).then(function () {
          done += 1;
          if (!failed) {
            status.textContent = MESSAGES.uploading(Math.min(done + 1, sending.length), sending.length);
          }
          return work();
        }, function () {
          if (!failed) {
            failed = true;
            fail(MESSAGES.failed(offset + i + 1));
          }
        });
      }
      status.textContent = MESSAGES.uploading(1, sending.length);
      var workers = [];
      for (var w = 0; w < AT_ONCE; w += 1) { workers.push(work()); }
      return Promise.all(workers).then(function () {
        if (failed) { return; }
        slots.forEach(function (slot) {
          var input = document.createElement("input");
          input.type = "hidden";
          input.name = "slot";
          input.value = slot.id;
          form.appendChild(input);
        });
        HTMLFormElement.prototype.submit.call(form);
      });
    }).catch(function () {
      fail(MESSAGES.tryAgain);
    });
  });
})();
