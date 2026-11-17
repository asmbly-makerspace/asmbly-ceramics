// A small DOM for running the drop-off form's upload.js in Node (decision 0009).
// It implements only what the script calls. A selector or a call it doesn't know throws,
// so a script change that needs more fails loudly instead of matching nothing.
// Node built-ins only: no npm package.
import vm from "node:vm";

class ClassList {
  constructor() { this.names = new Set(); }
  add(...names) { names.forEach((name) => this.names.add(name)); }
  remove(...names) { names.forEach((name) => this.names.delete(name)); }
  contains(name) { return this.names.has(name); }
}

class Element {
  constructor(document, tagName) {
    this.ownerDocument = document;
    this.tagName = tagName.toUpperCase();
    this.id = "";
    this.type = "";
    this.name = "";
    this.valueText = "";
    this.fileList = [];
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.min = "";
    this.max = "";
    this.src = "";
    this.alt = "";
    this.parentNode = null;
    this.children = [];
    this.classList = new ClassList();
    this.attributes = new Map();
    this.listeners = new Map();
    this.text = "";
  }

  // A file input's value is the path of its first file; setting it to "" empties its
  // files, as a browser does. Any other element just keeps the value.
  get value() { return this.valueText || ""; }
  set value(text) {
    this.valueText = String(text);
    if (this.type === "file" && this.valueText === "") { this.fileList = []; }
  }
  get files() { return this.fileList; }
  set files(list) { this.fileList = list; }

  get className() { return [...this.classList.names].join(" "); }
  set className(value) { this.classList.names = new Set(String(value).split(/\s+/).filter(Boolean)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  hasAttribute(name) { return this.attributes.has(name); }
  removeAttribute(name) { this.attributes.delete(name); }

  get textContent() { return this.text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    this.text = String(value);
  }

  appendChild(child) {
    if (child.parentNode) { child.remove(); }
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  remove() {
    if (!this.parentNode) { return; }
    const siblings = this.parentNode.children;
    siblings.splice(siblings.indexOf(this), 1);
    this.parentNode = null;
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) { this.listeners.set(type, []); }
    this.listeners.get(type).push(listener);
  }

  // Unlike a browser, a disabled element still gets the event: the tests prove the
  // script's own guards, not only the `disabled` flag.
  dispatch(type) {
    const event = { type, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
    (this.listeners.get(type) || []).slice().forEach((listener) => listener.call(this, event));
    return event;
  }

  click() {
    const clicks = this.ownerDocument.calls.clicks;
    if (this.id) { clicks[this.id] = (clicks[this.id] || 0) + 1; }
    return this.dispatch("click");
  }

  focus() { this.ownerDocument.activeElement = this; }

  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }

  querySelectorAll(selector) {
    const steps = parseSelector(selector);
    return nodeList(this.descendants().filter((element) => matchesSteps(element, steps)));
  }

  querySelector(selector) {
    const found = this.querySelectorAll(selector);
    return found.length ? found[0] : null;
  }
}

// What a browser's querySelectorAll returns is a NodeList, not an Array: it has a
// length, indexes and forEach, but no map, filter or the like. This stub's has only
// those three, so a script (or a test) that calls an Array method on one fails here as
// it would in a browser. Tests wrap one in Array.from to use Array methods.
function nodeList(elements) {
  const list = Object.create(null);
  elements.forEach((element, index) => {
    Object.defineProperty(list, index, { value: element, enumerable: true });
  });
  Object.defineProperty(list, "length", { value: elements.length });
  Object.defineProperty(list, "forEach", {
    value(callback, thisArg) { elements.forEach((element, index) => callback.call(thisArg, element, index, list)); },
  });
  return Object.freeze(list);
}

// A compound selector: tag, .class, #id, [name="value"] and :checked, in any order.
const PART = /^(?:([a-zA-Z][a-zA-Z0-9-]*)|\.([\w-]+)|#([\w-]+)|\[([\w-]+)="([^"]*)"\]|(:checked))/;

function parseCompound(text, selector) {
  const parts = [];
  let rest = text;
  while (rest.length) {
    const found = PART.exec(rest);
    if (!found || (found[1] && parts.length)) { throw new Error(`unsupported selector: ${selector}`); }
    parts.push(found);
    rest = rest.slice(found[0].length);
  }
  return (element) => parts.every((part) => {
    if (part[1]) { return element.tagName === part[1].toUpperCase(); }
    if (part[2]) { return element.classList.contains(part[2]); }
    if (part[3]) { return element.id === part[3]; }
    if (part[4]) { return element[part[4]] === part[5] || element.getAttribute(part[4]) === part[5]; }
    return element.checked === true;
  });
}

function parseSelector(selector) {
  if (/[,>+~*]/.test(selector)) { throw new Error(`unsupported selector: ${selector}`); }
  const compounds = selector.trim().split(/\s+/);
  if (!compounds[0]) { throw new Error(`unsupported selector: ${selector}`); }
  return compounds.map((text) => parseCompound(text, selector));
}

// The last compound matches the element; each earlier one an ancestor, anywhere above
// it, as a browser's element.querySelectorAll does.
function matchesSteps(element, steps) {
  if (!steps[steps.length - 1](element)) { return false; }
  let index = steps.length - 2;
  let node = element.parentNode;
  while (index >= 0 && node) {
    if (steps[index](node)) { index -= 1; }
    node = node.parentNode;
  }
  return index < 0;
}

class Document {
  constructor(calls) {
    this.calls = calls;
    this.activeElement = null;
    this.documentElement = new Element(this, "html");
    this.body = this.documentElement.appendChild(new Element(this, "body"));
  }

  createElement(tagName) { return new Element(this, tagName); }

  getElementById(id) {
    return this.documentElement.descendants().find((element) => element.id === id) || null;
  }
}

function make(document, parent, tagName, props = {}) {
  const element = document.createElement(tagName);
  const { className, attributes, ...rest } = props;
  Object.assign(element, rest);
  if (className) { element.className = className; }
  Object.entries(attributes || {}).forEach(([name, value]) => element.setAttribute(name, value));
  parent.appendChild(element);
  return element;
}

// The form as form.html renders it (the photo field's data-*, the pieces limits and a
// kept photo's classes come from the rendered page through the fixture), without the parts the photo list doesn't touch
// (the firing type radios, the glaze fieldset, the stepper): the script handles their
// absence. `fixture.ids` are the ids upload.js reads; each must exist here.
export function makeForm(fixture, options = {}) {
  const calls = { clicks: {}, revoked: [], fetched: [], appended: [], submitted: 0 };
  const document = new Document(calls);
  const form = make(document, document.body, "form", { id: "drop-off-form" });
  make(document, form, "input", { type: "hidden", name: "submission", value: "made-up-token" });
  make(document, form, "input", { id: "pieces", name: "pieces", type: "number", min: fixture.pieces.min, max: fixture.pieces.max, value: fixture.pieces.min });
  const field = make(document, form, "div", { id: "photos-field", className: "field photos", attributes: fixture.field });
  const errors = make(document, field, "div", { id: "photos-error", className: "photo-errors" });
  if (options.serverError) {
    make(document, errors, "p", { className: "field-error", textContent: options.serverError });
  }
  const list = make(document, field, "ul", { id: "photo-list", className: "photo-list" });
  for (let i = 0; i < (options.kept || 0); i += 1) {
    // The classes come from a kept photo on the rendered page (fixture.kept).
    const item = make(document, list, "li", { className: fixture.kept.item, attributes: { "data-slot": `made-up-slot-${i + 1}` } });
    make(document, item, "input", { type: "hidden", name: "slot", value: `made-up-slot-${i + 1}` });
    make(document, item, "span", { className: fixture.kept.label, textContent: "A photo you already added" });
    make(document, item, "button", { type: "button", className: fixture.kept.remove, textContent: "Remove" });
  }
  make(document, field, "input", { id: "photos", type: "file" });
  make(document, field, "button", { id: "take-photo", type: "button", hidden: true });
  make(document, field, "input", { id: "photos-camera", type: "file", hidden: true });
  make(document, form, "p", { id: "upload-status", className: "upload-status" });
  make(document, form, "button", { id: "submit-button", type: "submit" });

  const missing = fixture.ids.filter((id) => !document.getElementById(id));
  if (missing.length) { throw new Error(`the stub has no element for: ${missing.join(", ")}`); }

  let blobs = 0;
  const window = {};
  if (options.coarse !== undefined) {
    window.matchMedia = (query) => {
      if (query !== "(pointer: coarse)") { throw new Error(`unsupported media query: ${query}`); }
      return { matches: options.coarse };
    };
  }
  const fetch = options.fetch || ((url, init) => {
    calls.fetched.push({ url, init });
    return new Promise(() => {}); // never settles: the upload stays pending
  });
  class FormData {
    append(name, value) { calls.appended.push(name); }
  }
  function HTMLFormElement() {}
  HTMLFormElement.prototype.submit = function () { calls.submitted += 1; };
  const context = {
    document,
    window,
    URL: {
      createObjectURL() { blobs += 1; return `blob:${blobs}`; },
      revokeObjectURL(url) { calls.revoked.push(url); }
    },
    fetch,
    FormData,
    HTMLFormElement
  };
  const el = (id) => document.getElementById(id);
  return { context: vm.createContext(context), el, calls, document };
}

export function run(source, context) {
  vm.runInContext(source, context, { filename: "upload.js" });
}

// What a browser does when the person picks files: the input holds them, then "change".
export function pick(input, files) {
  input.files = files;
  input.value = files.length ? `made-up-path\\${files[0].name}` : "";
  input.dispatch("change");
}

// A made-up file: a name and a size, never contents.
export function photo(name, size, type = "image/jpeg") {
  return { name, size, type };
}
