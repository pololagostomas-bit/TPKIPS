"""Isolated Node/DOM-stub tests. No backend imports, network, Git or database."""
import pathlib
import shutil
import subprocess
import unittest


MODULE = pathlib.Path(__file__).resolve().parents[1] / "frontend/static/reception-np-scan.js"

HARNESS = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const nodes = new Map();
class Element {
  constructor(tag, attrs='') {
    this.tagName = tag.toUpperCase(); this.attrs = attrs; this.dataset = {};
    this.disabled = /\bdisabled\b/.test(attrs); this.readOnly = /\breadonly\b/.test(attrs);
    for (const [,name,value] of attrs.matchAll(/([\w-]+)="([^"]*)"/g)) {
      if (name === 'data-np-view') this.dataset.npView = value;
      else this[name] = value;
    }
    this.value ??= ''; this.children = []; this.textContent = '';
  }
  set innerHTML(html) {
    this.html = html; this.children = [];
    for (const [,tag,attrs] of html.matchAll(/<(input|button|select|textarea|section|div|td)\b([^>]*)>/g)) {
      const child = new Element(tag, attrs); this.children.push(child);
      if (child.id) nodes.set(child.id, child);
    }
  }
  get innerHTML() { return this.html; }
  querySelectorAll(selector) {
    if (selector === 'input[id^="qty-"]') return this.children.filter(e => e.tagName === 'INPUT' && e.id?.startsWith('qty-'));
    if (selector.startsWith('.np-scan-control')) return [];
    return [...nodes.values()].filter(e => ['INPUT','BUTTON','SELECT','TEXTAREA'].includes(e.tagName));
  }
  focus() { this.focused = true; }
  select() { this.selected = true; }
}
const document = {
  getElementById: id => nodes.get(id) || null,
  createElement: tag => {
    const element = new Element(tag);
    element.content = element;
    return element;
  }
};
const window = {};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {window, document});
const w = window.WmsNpScan;
const first = {id: 11, attention_id: 7, np_code: 'AB 01', description: '<b>pieza</b>',
  ov_number: 'OV-1', ip_reference: 'IP-1', default_location: 'A<&',
  attention_planned_qty: 9, stock_available_qty: 123456};
let shipment = {id: 5, attention_id: 7, app_status: 'REVISION SISTEMA', lines: [first]};
let selectedId = 5, attentionId = 7, editable = true;
let calls = [], notices = [], callbacks = [], onSaved = null;
let request = async () => ({ok: true, json: async () => ({id: 5, attention_id: 7})});
w.init({getContext: () => ({shipment, shipmentId: selectedId, attentionId}),
  panelEditable: name => { assert.equal(name, 'sistema'); return editable; },
  shipmentUrl: suffix => '/api/receptions/' + selectedId + suffix,
  api: (url, options) => { calls.push({url, options}); return request(); },
  notify: (...args) => notices.push(args),
  onSaved: (data, context) => { callbacks.push({data, context}); return onSaved?.(data, context); }
});
function mount(legacy) {
  nodes.clear();
  const html = w.render(shipment, legacy ?? shipment.lines.map(l =>
    `<input id="qty-${l.id}" type="number" value="9"><input id="reason-${l.id}" value="draft"><td id="diff-${l.id}"></td>`
  ).join('') + '<button data-save-physical-review onclick="savePhysicalReview()">Guardar revisión completa</button>');
  const root = new Element('main'); root.innerHTML = html;
  return html;
}
function scan(value=' ab 01 ') {
  const input = nodes.get('scanReceptionNp'); input.value = value;
  let prevented = false;
  w.handle({key: 'Enter', currentTarget: input, preventDefault() { prevented = true; }});
  assert(prevented);
}
function qty(value) { nodes.get('receptionNpQuantity').value = value; }
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is required")
class ReceptionNpScanUiTests(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run(
            [shutil.which("node"), "-e", HARNESS + "\n(async () => {\n" + script
             + "\n})().catch(error => {console.error(error); process.exitCode = 1;});", str(MODULE)],
            text=True, encoding="utf-8", capture_output=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_legacy_is_closed_and_manual_scan_result_is_escaped_without_stock(self):
        self.run_js(r"""
const html = mount();
assert(html.includes('<details><summary>Ver listado completo</summary>'));
assert(html.includes('savePhysicalReview()'));
assert.equal((html.match(/id="scanReceptionNp"/g) || []).length, 1);
assert(!html.includes('<details open'));
scan();
const result = nodes.get('receptionNpScanResult').innerHTML;
assert(result.includes('&lt;b&gt;pieza&lt;/b&gt;'));
assert(result.includes('Requerido: 9'));
assert(result.includes('A&lt;&amp;'));
assert(!result.includes('123456'));
assert.equal(nodes.get('receptionNpQuantity').value, '');
assert.equal(calls.length, 0);
""")

    def test_duplicate_np_requires_explicit_line_choice(self):
        self.run_js(r"""
shipment.lines.push({...first, id: 12, ov_number: 'OV-2', ip_reference: 'IP-2'});
mount(); scan();
const choices = nodes.get('receptionNpScanResult').innerHTML;
for (const text of ['OV-1', 'OV-2', 'IP-1', 'IP-2', '&lt;b&gt;pieza&lt;/b&gt;']) assert(choices.includes(text));
assert(!nodes.has('receptionNpQuantity'));
await w.save(); assert.equal(calls.length, 0);
w.choose(1); qty('3'); await w.save();
assert.equal(calls.length, 1);
assert.equal(calls[0].url, '/api/receptions/5/lines/12');
assert.equal(nodes.get('qty-11').value, '9');
""")

    def test_only_selected_line_and_captured_attention_are_sent(self):
        self.run_js(r"""
shipment.lines.push({...first, id: 12, np_code: 'OTHER'});
const before = JSON.stringify(shipment);
mount(); scan(); qty('0'); await w.save();
assert.equal(calls.length, 1);
assert.equal(calls[0].options.method, 'POST');
assert.equal(typeof calls[0].options.body, 'string');
assert.equal(calls[0].options.headers['Content-Type'], 'application/json');
assert.deepEqual(JSON.parse(calls[0].options.body), {received_qty: 0, reason: 'draft', attention_id: '7'});
assert.equal(nodes.get('qty-11').value, '0');
assert.equal(nodes.get('diff-11').textContent, '-9');
assert.equal(nodes.get('qty-12').value, '9');
assert.equal(JSON.stringify(shipment), before);
assert.equal(callbacks.length, 1);
assert(callbacks[0].context.isCurrent());
""")

    def test_blank_fraction_negative_infinite_and_unsafe_quantities_rejected(self):
        self.run_js(r"""
mount(); scan();
for (const value of ['', ' ', '1.5', '-1', 'NaN', 'Infinity', '1e3', '9007199254740992']) {
  qty(value); await w.save(); assert.equal(calls.length, 0);
}
qty('12'); await w.save(); // excess is valid; expected quantity is not a cap
assert.equal(calls.length, 1);
""")

    def test_permissions_require_existing_enabled_quantity_inputs(self):
        self.run_js(r"""
editable = false; mount(); assert(nodes.get('scanReceptionNp').disabled);
editable = true; mount('<p>No qty inputs, even for admin.</p>');
assert(nodes.get('scanReceptionNp').disabled);
mount('<input id="qty-11" type="number" disabled>');
assert(nodes.get('scanReceptionNp').disabled);
mount('<input id="qty-11" type="number" readonly>');
assert(nodes.get('scanReceptionNp').disabled);
mount(); scan(); qty('2'); editable = false; await w.save();
assert.equal(calls.length, 0);
""")

    def test_disabled_duplicate_is_not_silently_skipped(self):
        self.run_js(r"""
shipment.lines.push({...first, id: 12});
mount('<input id="qty-11" type="number"><input id="qty-12" type="number" disabled>');
scan(); assert(!nodes.has('receptionNpQuantity'));
w.choose(1); assert(!nodes.has('receptionNpQuantity'));
w.choose(0); assert(nodes.has('receptionNpQuantity'));
""")

    def test_request_disables_submit_and_failure_preserves_draft(self):
        self.run_js(r"""
let finish;
request = () => new Promise(resolve => { finish = resolve; });
mount(); scan(); qty('4'); nodes.get('receptionNpReason').value = 'contado';
const saving = w.save();
assert(nodes.get('receptionNpSave').disabled);
assert(nodes.get('scanReceptionNp').disabled);
await w.save(); assert.equal(calls.length, 1);
finish({ok: false, json: async () => ({error: 'Fallo controlado'})}); await saving;
assert.equal(nodes.get('receptionNpQuantity').value, '4');
assert.equal(nodes.get('receptionNpReason').value, 'contado');
assert(!nodes.get('receptionNpSave').disabled);
assert.equal(nodes.get('qty-11').value, '9');
assert.equal(callbacks.length, 0);
""")

    def test_network_and_invalid_json_keep_quantity(self):
        self.run_js(r"""
mount(); scan(); qty('4');
request = async () => { throw new Error('offline'); };
await w.save(); assert.equal(nodes.get('receptionNpQuantity').value, '4');
request = async () => ({ok: true, json: async () => { throw new Error('bad JSON'); }});
await w.save(); assert.equal(nodes.get('receptionNpQuantity').value, '4');
assert(!nodes.get('receptionNpSave').disabled);
""")

    def test_navigation_during_save_cannot_mutate_other_attention(self):
        self.run_js(r"""
let finish;
request = () => new Promise(resolve => { finish = resolve; });
mount(); scan(); qty('4'); const saving = w.save();
shipment = {...shipment, attention_id: 8, lines: [{...first, attention_id: 8}]};
attentionId = 8; mount();
finish({ok: true, json: async () => ({id: 5, attention_id: 7})}); await saving;
assert.equal(callbacks.length, 0);
assert.equal(nodes.get('qty-11').value, '9');
assert(!nodes.get('scanReceptionNp').disabled);
assert.equal(JSON.parse(calls[0].options.body).attention_id, '7');
""")

    def test_stale_selection_and_line_attention_are_rejected(self):
        self.run_js(r"""
mount(); scan(); qty('4'); attentionId = 8; await w.save();
assert.equal(calls.length, 0);
attentionId = 7; selectedId = 6; await w.save(); assert.equal(calls.length, 0);
selectedId = 5; first.attention_id = 8; mount(); scan();
assert(!nodes.has('receptionNpQuantity'));
""")

    def test_mismatched_response_is_not_applied(self):
        self.run_js(r"""
mount(); scan(); qty('4');
request = async () => ({ok: true, json: async () => ({id: 5, attention_id: 99})});
await w.save();
assert.equal(callbacks.length, 0);
assert.equal(nodes.get('qty-11').value, '9');
assert.equal(nodes.get('receptionNpQuantity').value, '4');
""")

    def test_callback_guard_expires_after_new_render(self):
        self.run_js(r"""
mount(); scan(); qty('4');
onSaved = (_data, context) => { assert(context.isCurrent()); mount(); assert(!context.isCurrent()); };
await w.save();
assert.equal(callbacks.length, 1);
assert(!nodes.get('scanReceptionNp').disabled);
""")

    def test_unknown_np_and_non_enter_never_save(self):
        self.run_js(r"""
mount(); scan('missing'); assert.equal(calls.length, 0);
assert(!nodes.has('receptionNpQuantity'));
w.handle({key: 'Escape', preventDefault() { throw Error('unexpected'); }});
assert.equal(calls.length, 0);
""")

    def test_real_template_cells_keep_admin_out_of_non_quantity_stages(self):
        self.run_js(r"""
const path = require('node:path');
const template = fs.readFileSync(path.join(path.dirname(process.argv[1]), '../templates/reception.html'), 'utf8');
const source = template.match(/function physicalLineCells\(line,status\)\{[^\r\n]+/)[0];
const cells = vm.runInNewContext('(' + source + ')', {
  esc: value => String(value ?? '').replace(/</g, '&lt;')
});
editable = true; // panelEditable returns true for administrator at any stage
shipment.app_status = 'EM';
mount(cells(first, 'EM'));
assert(nodes.get('scanReceptionNp').disabled);
shipment.app_status = 'REVISION SISTEMA';
first.attention_system_initialized = 0;
mount(cells(first, shipment.app_status));
assert.equal(nodes.get('qty-11').value, '9'); // actual template's 100% default
scan(); assert.equal(nodes.get('receptionNpQuantity').value, '');
await w.save(); assert.equal(calls.length, 0);
""")

    def test_status_change_during_request_does_not_reenable_controls(self):
        self.run_js(r"""
let finish;
request = () => new Promise(resolve => { finish = resolve; });
mount(); scan(); qty('4'); const saving = w.save();
shipment.app_status = 'EM'; editable = false;
finish({ok: true, json: async () => ({id: 5, attention_id: 7})}); await saving;
assert(nodes.get('receptionNpSave').disabled);
assert(nodes.get('scanReceptionNp').disabled);
assert.equal(callbacks.length, 0);
""")

    def test_callback_failure_does_not_report_a_failed_server_save(self):
        self.run_js(r"""
mount(); scan(); qty('4');
onSaved = () => { throw new Error('render failed'); };
await w.save();
assert.equal(nodes.get('qty-11').value, '4');
assert.equal(nodes.get('receptionNpQuantity').value, '4');
assert(notices.at(-1)[0].includes('La línea se guardó'));
assert(!nodes.get('receptionNpSave').disabled);
""")


if __name__ == '__main__':
    unittest.main()
