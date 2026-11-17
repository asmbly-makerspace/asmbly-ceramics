// The drop-off form's upload.js, run in Node against the stub in dom.mjs (decision 0009).
// Started by tests/web/test_upload_script.py, which hands over the real form's photo
// field (its limits and sentences) and the script's path. File names are made up and
// files are sizes only, never contents.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { makeForm, run, pick, photo } from "./dom.mjs";

if (!process.env.UPLOAD_FORM || !process.env.UPLOAD_SCRIPT) {
  throw new Error("run me through tests/web/test_upload_script.py");
}
const fixture = JSON.parse(readFileSync(process.env.UPLOAD_FORM, "utf8"));
const SOURCE = readFileSync(process.env.UPLOAD_SCRIPT, "utf8");
const field = fixture.field;
const MAX = parseInt(field["data-photos-max"], 10);
const MAX_BYTES = parseInt(field["data-photo-max-bytes"], 10);
const COUNT = field["data-message-count"];
const tooLarge = (n) => field["data-message-too-large"].replace("{n}", String(n));

function start(options) {
  const page = makeForm(fixture, options);
  run(SOURCE, page.context);
  return page;
}

const items = (page) => page.el("photo-list").querySelectorAll(".photo-item");
const labels = (page) => Array.from(items(page)).map((item) => item.querySelector(".photo-label").textContent);
const removeLabels = (page) => Array.from(items(page)).map((item) => item.querySelector(".remove").getAttribute("aria-label"));
const errorTexts = (page) => Array.from(page.el("photos-error").querySelectorAll("p")).map((p) => p.textContent);
const statusText = (page) => page.el("upload-status").textContent;
const removeAt = (page, i) => items(page)[i].querySelector(".remove").click();
const pots = (from, count, size = 1000) =>
  Array.from({ length: count }, (_, i) => photo(`pot-${from + i}.jpg`, size));

test("the limits come from the page", () => {
  assert.ok(MAX >= 2, "the form's photo limit");
  assert.ok(MAX_BYTES > 1000, "the form's size limit");
  assert.ok(field["data-message-too-large"].includes("{n}"));
});

test("a library pick adds each photo in order, named by its file", () => {
  const page = start();
  pick(page.el("photos"), pots(1, 2));
  assert.deepEqual(labels(page), ["pot-1.jpg", "pot-2.jpg"]);
  assert.deepEqual(removeLabels(page), ["Remove photo 1", "Remove photo 2"]);
  assert.equal(statusText(page), `Photo 2 of ${MAX} added`);
  assert.equal(page.el("photos").value, "", "cleared, so the same file can be picked again");
  assert.equal(page.el("photos").files.length, 0, "clearing the value empties the files, as in a browser");
  assert.deepEqual(errorTexts(page), []);
});

test("a camera shot is called by its place, and the labels renumber after a removal", () => {
  const page = start({ coarse: true });
  pick(page.el("photos"), pots(1, 1));
  pick(page.el("photos-camera"), [photo("image.jpg", 1000)]);
  pick(page.el("photos-camera"), [photo("image.jpg", 1000)]);
  assert.deepEqual(labels(page), ["pot-1.jpg", "Photo 2", "Photo 3"]);
  assert.equal(statusText(page), `Photo 3 of ${MAX} added`);
  assert.equal(page.el("photos-camera").value, "");

  removeAt(page, 0);
  assert.deepEqual(labels(page), ["Photo 1", "Photo 2"]);
  assert.deepEqual(removeLabels(page), ["Remove photo 1", "Remove photo 2"]);
  assert.equal(statusText(page), "");
  assert.deepEqual(page.calls.revoked, ["blob:1"], "the removed photo's preview is let go");
});

test("a full list disables both inputs and the button, and a removal enables them", () => {
  const page = start({ coarse: true });
  const controls = () => ["photos", "photos-camera", "take-photo"].map((id) => page.el(id).disabled);
  pick(page.el("photos"), pots(1, MAX - 1));
  assert.deepEqual(controls(), [false, false, false]);
  pick(page.el("photos-camera"), [photo("image.jpg", 1000)]);
  assert.equal(items(page).length, MAX);
  assert.deepEqual(controls(), [true, true, true]);

  removeAt(page, 2);
  assert.equal(items(page).length, MAX - 1);
  assert.deepEqual(controls(), [false, false, false]);
});

test("picks past the limit are refused with the count message once", () => {
  const page = start();
  pick(page.el("photos"), pots(1, MAX - 1));
  pick(page.el("photos"), pots(MAX, 3));
  assert.equal(items(page).length, MAX);
  assert.deepEqual(labels(page).slice(-1), [`pot-${MAX}.jpg`], "the first of the pick is kept");
  assert.deepEqual(errorTexts(page), [COUNT]);
  assert.equal(statusText(page), COUNT);
});

test("focus leaves a control that the full list disables", () => {
  const page = start();
  page.el("photos").focus();
  pick(page.el("photos"), pots(1, MAX));
  assert.equal(page.el("photos").disabled, true);
  assert.equal(page.document.activeElement, page.el("submit-button"));
});

test("an over-size photo gets its message when added, and the message follows it", () => {
  const page = start();
  pick(page.el("photos"), [photo("pot-1.jpg", 1000), photo("pot-2.jpg", MAX_BYTES + 1)]);
  assert.equal(items(page).length, 2, "kept in the list, so the person sees which one");
  assert.deepEqual(errorTexts(page), [tooLarge(2)]);
  assert.equal(statusText(page), tooLarge(2));

  removeAt(page, 0);
  assert.deepEqual(errorTexts(page), [tooLarge(1)]);

  removeAt(page, 0);
  assert.deepEqual(errorTexts(page), []);
  assert.equal(page.el("photos-error").hasAttribute("data-script"), false);
});

test("a photo of exactly the size limit gets no message", () => {
  const page = start();
  pick(page.el("photos"), [photo("pot-1.jpg", MAX_BYTES)]);
  assert.deepEqual(errorTexts(page), []);
  assert.equal(statusText(page), `Photo 1 of ${MAX} added`);
});

test("kept photos count first and the server's own message survives a removal", () => {
  const page = start({ kept: 2 });
  assert.deepEqual(removeLabels(page), ["Remove kept photo 1 of 2", "Remove kept photo 2 of 2"]);
  pick(page.el("photos"), pots(1, 1));
  assert.deepEqual(removeLabels(page), ["Remove kept photo 1 of 2", "Remove kept photo 2 of 2", "Remove photo 3"]);
  assert.equal(statusText(page), `Photo 3 of ${MAX} added`);
  pick(page.el("photos"), [photo("pot-2.jpg", MAX_BYTES + 1)]);
  assert.deepEqual(errorTexts(page), [tooLarge(4)], "numbered after the kept photos");
  removeAt(page, 0);
  assert.deepEqual(errorTexts(page), [tooLarge(3)], "a kept photo's Remove renumbers the size message");
  assert.equal(statusText(page), "", "and clears the status line");

  const serverMessage = tooLarge(1); // any of the form's own sentences
  const refused = start({ kept: 2, serverError: serverMessage });
  removeAt(refused, 0);
  assert.deepEqual(errorTexts(refused), [serverMessage]);
  assert.deepEqual(removeLabels(refused), ["Remove kept photo 1 of 1"]);
});

test("the camera button shows only on a touch screen and opens the camera", () => {
  const touch = start({ coarse: true });
  assert.equal(touch.el("take-photo").hidden, false);
  touch.el("take-photo").click();
  assert.equal(touch.calls.clicks["photos-camera"], 1);

  for (const coarse of [false, undefined]) {
    const page = start({ coarse });
    assert.equal(page.el("take-photo").hidden, true, `matchMedia: ${coarse}`);
    page.el("take-photo").click();
    assert.equal(page.calls.clicks["photos-camera"], undefined);
  }
});

test("too few photos stop the submit before anything is sent", () => {
  const page = start();
  const event = page.el("drop-off-form").dispatch("submit");
  assert.equal(event.defaultPrevented, true);
  assert.deepEqual(errorTexts(page), [COUNT]);
  assert.deepEqual(page.calls.fetched, []);
  assert.equal(page.calls.submitted, 0);
  assert.equal(page.el("submit-button").disabled, false);
});

test("an over-size photo stops the submit before anything is sent", () => {
  const page = start();
  pick(page.el("photos"), [photo("pot-1.jpg", MAX_BYTES + 1)]);
  page.el("drop-off-form").dispatch("submit");
  assert.deepEqual(errorTexts(page), [tooLarge(1)]);
  assert.deepEqual(page.calls.fetched, []);
});

test("the list is locked while its photos upload", () => {
  const page = start({ kept: 1, coarse: true });
  pick(page.el("photos"), pots(1, 1));
  page.el("drop-off-form").dispatch("submit");

  assert.equal(page.calls.fetched.length, 1);
  assert.equal(page.calls.fetched[0].url, "/drop-off/uploads");
  assert.deepEqual(JSON.parse(page.calls.fetched[0].init.body), { count: 1, submission: "made-up-token" });
  for (const id of ["submit-button", "photos", "photos-camera", "take-photo"]) {
    assert.equal(page.el(id).disabled, true, id);
  }
  assert.deepEqual(Array.from(items(page)).map((item) => item.querySelector(".remove").disabled), [true, true]);

  removeAt(page, 0);
  removeAt(page, 1);
  pick(page.el("photos"), pots(2, 1));
  pick(page.el("photos-camera"), [photo("image.jpg", 1000)]);
  page.el("take-photo").click();
  assert.equal(items(page).length, 2, "nothing removed or added mid-upload");
  assert.equal(page.calls.clicks["photos-camera"], undefined, "the camera stays shut");
  page.el("drop-off-form").dispatch("submit");
  assert.equal(page.calls.fetched.length, 1, "a second submit sends nothing");
});

test("kept photos alone are submitted with no upload", () => {
  const page = start({ kept: 1 });
  page.el("drop-off-form").dispatch("submit");
  assert.deepEqual(page.calls.fetched, []);
  assert.equal(page.calls.submitted, 1);
});
