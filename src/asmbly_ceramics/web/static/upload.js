// The drop-off form's photo upload and its small conveniences (decision 0002).
// A plain script: no build step, no library, no inline script. Every check here is for
// the person's convenience only; the server checks everything again.
(function () {
  "use strict";

  document.documentElement.classList.add("js");

  var form = document.getElementById("drop-off-form");
  if (!form) { return; }
  var field = document.getElementById("photos-field");
  // The limits and the server's sentences come from the server (domain/limits.py and
  // web/fields.py); the short labels for the list ("Photo 2", "Remove photo 2") are the
  // script's own.
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
  var camera = document.getElementById("photos-camera");
  var takePhoto = document.getElementById("take-photo");
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

  // The server's refusal messages are in `errors` too; the ones the script puts there are
  // marked, so a Remove rewrites only those.
  function showErrors(messages) {
    errors.textContent = "";
    if (messages.length) { errors.setAttribute("data-script", "true"); } else { errors.removeAttribute("data-script"); }
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
  // A full list takes no more photos either.
  var busy = false;
  function updateControls() {
    var full = keptCount() + chosen.length >= PHOTOS_MAX;
    var active = document.activeElement;
    if (!busy && full && (active === picker || active === camera || active === takePhoto)) {
      submit.focus(); // a disabled control would drop the keyboard's place to the top
    }
    picker.disabled = busy || full;
    camera.disabled = busy || full;
    takePhoto.disabled = busy || full;
  }
  function setBusy(value) {
    busy = value;
    submit.disabled = value;
    list.querySelectorAll(".remove").forEach(function (button) { button.disabled = value; });
    updateControls();
  }

  // The photos over the size limit, by their place in the list. Built from the list each
  // time, so a removed photo takes its message with it and the numbers stay right.
  function sizeMessages() {
    var out = [];
    chosen.forEach(function (entry, i) {
      if (entry.file.size > PHOTO_MAX_BYTES) { out.push(MESSAGES.tooLarge(keptCount() + i + 1)); }
    });
    return out;
  }

  function refreshErrors() {
    if (errors.hasAttribute("data-script")) { showErrors(sizeMessages()); }
  }

  // The label of each photo is its place in the list, so a screen reader hears which Remove
  // is which. A camera shot has no useful file name (a phone names every one the same).
  function renumber() {
    var keptTotal = keptCount();
    var kept = 0;
    list.querySelectorAll(".photo-item").forEach(function (item, i) {
      var remove = item.querySelector(".remove");
      if (item.classList.contains("photo-kept")) {
        // The server's messages number the photos as the person sent them, which a refused
        // photo changes, so a kept photo is never called by a position that may not match.
        kept += 1;
        remove.setAttribute("aria-label", "Remove kept photo " + kept + " of " + keptTotal);
        return;
      }
      remove.setAttribute("aria-label", "Remove photo " + (i + 1));
      if (item.hasAttribute("data-camera")) {
        item.querySelector(".photo-label").textContent = "Photo " + (i + 1);
      }
    });
    updateControls();
  }
  renumber();

  // Photos already uploaded and kept by the server after a refused submit.
  list.querySelectorAll(".photo-kept .remove").forEach(function (button) {
    button.addEventListener("click", function () {
      if (busy) { return; }
      button.parentNode.remove();
      status.textContent = "";
      refreshErrors();
      renumber();
    });
  });

  // Each pick adds to the list, from the library or from the camera: a phone's camera
  // returns one photo per pick. The files are copied, then the input is cleared so the
  // same file can be picked again.
  function addFiles(input, fromCamera) {
    if (busy) { input.value = ""; return; }
    status.textContent = "";
    var files = Array.prototype.slice.call(input.files);
    var messages = [];
    var added = 0;
    files.forEach(function (file) {
      if (keptCount() + chosen.length >= PHOTOS_MAX) {
        if (messages.indexOf(MESSAGES.count) < 0) { messages.push(MESSAGES.count); }
        return;
      }
      var entry = { file: file, url: URL.createObjectURL(file) };
      chosen.push(entry);
      added += 1;
      var item = document.createElement("li");
      item.className = "photo-item";
      if (fromCamera) { item.setAttribute("data-camera", "true"); }
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
        status.textContent = "";
        refreshErrors();
        renumber();
      }));
      list.appendChild(item);
    });
    messages = messages.concat(sizeMessages());
    showErrors(messages);
    input.value = "";
    renumber();
    if (messages.length) {
      status.textContent = messages[0]; // where the person is looking, beside the buttons
    } else if (added) {
      status.textContent = "Photo " + (keptCount() + chosen.length) + " of " + PHOTOS_MAX + " added";
    }
  }
  picker.addEventListener("change", function () { addFiles(picker, false); });
  camera.addEventListener("change", function () { addFiles(camera, true); });

  // The camera button is for phones and tablets: a desktop browser ignores `capture` and
  // would open the same file picker twice.
  if (window.matchMedia && window.matchMedia("(pointer: coarse)").matches) {
    takePhoto.hidden = false;
    takePhoto.addEventListener("click", function () {
      if (!busy) { camera.click(); }
    });
  }

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
    var tooLarge = sizeMessages();
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
