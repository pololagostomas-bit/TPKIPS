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
  querySelector() { return null; }
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
  // Explicit correction remains available, independent of automatic Enter scans.
  return w.review(value);
}
function automatic(value=' ab 01 ') {
  const input=nodes.get('scanReceptionNp'); input.value=value;
  return w.handle({key:'Enter',currentTarget:input,preventDefault(){}});
}
function confirmReads() {
  request=async()=>({ok:true,json:async()=>({id:5,attention_id:7,lines:shipment.lines.map(line=>({
    ...line,np_scanned_at:'2026-10-14 10:00:00',attention_verified_qty:JSON.parse(calls.at(-1).options.body).received_qty
  }))})});
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

    def test_data_matrix_prefix_survives_hid_caps_and_duplicate_pending_callbacks(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,ov_number:'OV-2'});mount();confirmReads();
await automatic(']D1AB01');assert(w.hasPending());
assert(String(nodes.get('receptionNpScanResult').innerHTML || '').includes('OV-1'),'Uppercase HID prefix must resolve the existing NP');
await automatic(']d1AB01');assert.equal(calls.length,0);
await w.choose(0);assert.equal(calls.length,1);assert(!w.hasPending());
await automatic(']D1AB01');assert.equal(calls.length,2);assert(w.canComplete());
""")

    def test_literal_np_starting_with_symbology_text_is_not_stripped(self):
        self.run_js(r"""
first.np_code=']D1AB01';mount();confirmReads();
await automatic(']D1AB01');assert.equal(calls.length,1);assert(w.canComplete());
""")

    def test_enter_saves_full_quantity_without_confirmation_and_persists_progress(self):
        self.run_js(r"""
mount();confirmReads();
assert.equal(w.canComplete(),false);
await automatic();
assert.equal(calls.length,1);
assert.deepEqual(JSON.parse(calls[0].options.body),{received_qty:9,reason:'draft',scan_np:true,attention_id:'7'});
assert(!nodes.has('receptionNpQuantity'));
assert.equal(nodes.get('receptionNpProgress').textContent,'NP leidos: 1/1');
assert(w.canComplete());assert(!w.hasPending());
await automatic();assert.equal(calls.length,1);
assert(nodes.get('receptionNpScanResult').textContent.includes('ya revisado'));
assert.equal(nodes.get('qty-11').value,'9');
first.np_scanned_at='2026-10-14';mount();assert(w.canComplete());
""")

    def test_real_unreceived_exception_resolves_pending_without_faking_a_scan(self):
        self.run_js(r"""
first.np_unreceived_reason='No llego este NP <script>';const html=mount();
assert(w.canComplete());
assert(html.includes('NP leidos: 0/1'));assert(html.includes('No recibidos: 1'));
assert(html.includes('No recibido'));assert(html.includes('&lt;script&gt;'));
assert.equal(calls.length,0);
""")

    def test_rapid_reads_are_queued_serially_and_unknown_read_must_be_resolved(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,np_code:'OTHER'});mount();
let finish;
request=()=>new Promise(resolve=>{finish=resolve});
const saving=automatic();
assert(!nodes.get('scanReceptionNp').disabled);
automatic('OTHER');assert.equal(calls.length,1);assert(w.hasPending());
assert.equal(w.canComplete(),false);
confirmReads();
finish({ok:true,json:async()=>({id:5,attention_id:7,lines:[{id:11,np_scanned_at:'now',attention_verified_qty:9}]})});
await saving;
assert.equal(calls.length,2);assert(w.canComplete());
await automatic('MISSING');assert(w.hasPending());
await automatic('OTHER');assert(w.hasPending());assert.equal(calls.length,2);
await w.discard();assert(!w.hasPending());assert.equal(calls.length,2);
""")

    def test_failed_auto_save_keeps_queue_and_requires_explicit_retry(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,np_code:'OTHER'});mount();
request=async()=>({ok:false,json:async()=>({error:'offline'})});
await automatic();assert.equal(calls.length,1);assert(w.hasPending());
await automatic('OTHER');assert.equal(calls.length,1);
assert.equal(nodes.get('qty-11').value,'9');
confirmReads();await w.retry();
assert.equal(calls.length,3);assert(!w.hasPending());assert(w.canComplete());
assert.deepEqual(JSON.parse(calls[0].options.body),JSON.parse(calls[1].options.body));
""")

    def test_ambiguous_auto_read_chooses_order_but_never_asks_quantity(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,ov_number:'OV-2'});mount();confirmReads();
await automatic();assert.equal(calls.length,0);assert(w.hasPending());
await w.choose(1);assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/receptions/5/lines/12');
assert(!nodes.has('receptionNpQuantity'));assert.equal(w.canComplete(),false);
await automatic();await w.choose(0);
assert.equal(calls.length,2);assert(w.canComplete());
assert.equal(nodes.get('receptionNpProgress').textContent,'NP leidos: 1/1');
""")

    def test_auto_response_without_scan_marker_is_not_counted_and_corrected_zero_is_kept(self):
        self.run_js(r"""
mount('<input id="qty-11" type="number" value="0">');
await automatic();assert(w.hasPending());assert.equal(w.canComplete(),false);
assert.equal(JSON.parse(calls[0].options.body).received_qty,0);
confirmReads();await w.retry();assert(w.canComplete());
assert.equal(nodes.get('qty-11').value,'0');
w.review();assert.equal(nodes.get('receptionNpQuantity').value,'0');
""")

    def test_legacy_is_closed_and_scan_result_is_escaped_with_full_quantity_without_stock_amount(self):
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
assert.equal(nodes.get('receptionNpQuantity').value, '9');
assert(result.includes('class="np-reference-info help-guidance"'));
assert(result.includes('Ubicación por defecto'));
assert(!result.includes('Ubicación de conteo'));
assert.equal(calls.length, 0);
""")

    def test_quantity_defaults_preserve_current_integer_zero_and_require_explicit_save(self):
        self.run_js(r"""
for (const value of ['9','3','0']) {
  mount(`<input id="qty-11" type="number" value="${value}">`); scan();
  assert.equal(nodes.get('receptionNpQuantity').value, value);
  assert.equal(calls.length, 0);
}
mount('<input id="qty-11" type="number" value="">'); scan();
assert.equal(nodes.get('receptionNpQuantity').value, '9');
mount('<input id="qty-11" type="number" value="1.5">'); scan();
assert.equal(nodes.get('receptionNpQuantity').value, '1.5');
await w.save();assert.equal(calls.length,0); // invalid draft is not silently replaced
first.attention_planned_qty=2.5;
mount('<input id="qty-11" type="number" value="">'); scan();
assert.equal(nodes.get('receptionNpQuantity').value, ''); // do not round real quantities
await w.save();assert.equal(calls.length,0);
""")

    def test_only_zero_stock_shows_status_never_a_stock_quantity(self):
        self.run_js(r"""
first.stock_available_qty=0;mount();scan();
assert(nodes.get('receptionNpScanResult').innerHTML.includes('Sin stock'));
first.stock_available_qty=123456;mount();scan();
const html=nodes.get('receptionNpScanResult').innerHTML;
assert(!html.includes('Sin stock'));assert(!html.includes('123456'));
""")

    def test_plain_data_matrix_aim_prefix_is_removed_only_from_input(self):
        self.run_js(r"""
first.np_code='ICM/2022-273.a';mount();scan(']d1ICM/2022-273.a');
assert(nodes.get('receptionNpQuantity'));assert.equal(calls.length,0);
mount();scan(']d2ICM/2022-273.a');
assert(!nodes.has('receptionNpQuantity'));
first.np_code=']d1ICM/2022-273.a';mount();scan('ICM/2022-273.a');
assert(!nodes.has('receptionNpQuantity'));
""")

    def test_duplicate_np_requires_explicit_line_choice(self):
        self.run_js(r"""
shipment.lines.push({...first, id: 12, ov_number: 'OV-2', ip_reference: 'IP-2'});
mount(); scan();
const choices = nodes.get('receptionNpScanResult').innerHTML;
for (const text of ['OV-1', 'OV-2', 'IP-1', 'IP-2', '&lt;b&gt;pieza&lt;/b&gt;']) assert(choices.includes(text));
assert.equal((choices.match(/class="ghost np-match"/g)||[]).length,2);
assert(!choices.includes('<details'));
assert(choices.includes('Pedido 1'));assert(choices.includes('Pedido 2'));
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

    def test_same_source_id_in_payload_is_not_a_second_order_or_second_scan(self):
        self.run_js(r"""
shipment.lines.push({...first,id:'11'});mount();confirmReads();
assert.equal(w.countLines(shipment).length,1);
await automatic();assert.equal(calls.length,1);
assert(!nodes.get('receptionNpScanResult').innerHTML.includes('np-match'));
assert.equal(nodes.get('receptionNpProgress').textContent,'NP leidos: 1/1');
assert(w.canComplete());await automatic();assert.equal(calls.length,1);
""")

    def test_other_arrival_does_not_create_false_ambiguity_or_a_foreign_write(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,in_selected_attention:false,ov_number:'OLD-OV'},
                    {...first,id:13,attention_id:8,ov_number:'OTHER-OV'});
mount();confirmReads();await automatic();
assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/receptions/5/lines/11');
assert.equal(nodes.get('receptionNpProgress').textContent,'NP leidos: 1/1');assert(w.canComplete());
shipment.lines.push({...first,id:14,np_code:'OLD-ONLY',in_selected_attention:false});
mount();await automatic('OLD-ONLY');assert.equal(calls.length,1);assert(w.hasPending());
assert(nodes.get('receptionNpScanResult').textContent.includes('otra llegada'));
assert(!notices.some(([text])=>text.includes('otra llegada'))); // inline issue cannot linger in another BL's toast
await w.discard();assert(!w.hasPending());
""")

    def test_legitimate_orders_with_and_without_ov_stay_separate_and_only_pending_are_offered(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,ov_number:'',ip_reference:'IP-2'},
                    {...first,id:13,ov_number:'OV-2',ip_reference:'IP-3'});
mount();confirmReads();await automatic();
let choices=nodes.get('receptionNpScanResult').innerHTML;
assert(choices.includes('Sin OV'));assert(choices.includes('OV-1'));assert(choices.includes('OV-2'));
assert.equal((choices.match(/class="ghost np-match"/g)||[]).length,3);
await w.choose(1);assert.equal(calls[0].url,'/api/receptions/5/lines/12');
await automatic();choices=nodes.get('receptionNpScanResult').innerHTML;
assert(!choices.includes('Sin OV'));assert.equal((choices.match(/class="ghost np-match"/g)||[]).length,2);
await w.choose(1);assert.equal(calls[1].url,'/api/receptions/5/lines/13');
await automatic();assert.equal(calls[2].url,'/api/receptions/5/lines/11');
assert.equal(calls.length,3);assert(w.canComplete());assert(!nodes.has('receptionNpQuantity'));
await automatic();assert.equal(calls.length,3);
""")

    def test_distinct_source_ids_are_never_merged_by_np_ov_ip_or_quantity(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12});mount();confirmReads();await automatic();
assert.equal(calls.length,0);assert.equal(w.countLines(shipment).length,2);
assert.equal((nodes.get('receptionNpScanResult').innerHTML.match(/class="ghost np-match"/g)||[]).length,2);
await w.choose(0);assert.equal(calls.length,1);assert(!w.canComplete());
await automatic();assert.equal(calls.length,2);assert(w.canComplete());
""")

    def test_zero_balance_rows_from_an_earlier_arrival_are_not_pending_orders(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,ov_number:'OLD-OV',attention_planned_qty:0,attention_verified_qty:0,received_qty:9},
                    {...first,id:13,np_code:'OLD-ONLY',attention_planned_qty:0,attention_verified_qty:0,received_qty:9});
mount();confirmReads();await automatic();
assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/receptions/5/lines/11');assert(w.canComplete());
await automatic('OLD-ONLY');assert.equal(calls.length,1);assert(w.hasPending());
assert(nodes.get('receptionNpIssue').innerHTML.includes('no tiene cantidad pendiente'));
await w.discard();w.review('AB01');
assert.equal((nodes.get('receptionNpScanResult').innerHTML.match(/class="ghost np-match"/g)||[]).length,2);
""")

    def test_repeated_callback_while_saving_or_choosing_cannot_consume_another_order(self):
        self.run_js(r"""
shipment.lines.push({...first,id:12,ov_number:'OV-2'});mount();
let finish;request=()=>new Promise(resolve=>{finish=resolve});
await automatic();await automatic(']d1ab 01');
assert.equal(calls.length,0);assert(w.hasPending());
const saving=w.choose(0);await automatic('AB01');assert.equal(calls.length,1);
finish({ok:true,json:async()=>({id:5,attention_id:7,lines:[{id:11,np_scanned_at:'now',attention_verified_qty:9}]})});
await saving;assert.equal(calls.length,1);assert(!w.hasPending());assert(!w.canComplete());
confirmReads();await automatic();assert.equal(calls.length,2);assert(w.canComplete());
""")

    def test_already_read_and_real_missing_orders_are_not_offered_again(self):
        self.run_js(r"""
first.np_scanned_at='now';shipment.lines.push({...first,id:12,np_scanned_at:null,np_unreceived_reason:'No llego'},
                                           {...first,id:13,np_scanned_at:null,ov_number:'OV-3'});
mount();confirmReads();await automatic();
assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/receptions/5/lines/13');
assert(w.canComplete());
w.review('AB01');assert.equal((nodes.get('receptionNpScanResult').innerHTML.match(/class="ghost np-match"/g)||[]).length,3);
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

    def test_count_location_is_sent_only_for_the_chosen_line_and_saved_without_clearing_other_drafts(self):
        self.run_js(r"""
shipment.lines.push({...first, id: 12, np_code: 'OTHER'});
mount('<input id="qty-11" type="number" value="9"><input id="reason-11" value="draft">' +
  '<input id="count-location-11" value="BIN-01"><td id="diff-11"></td>' +
  '<input id="qty-12" type="number" value="5"><input id="count-location-12" value="UNSAVED">');
scan();
assert.equal(nodes.get('receptionNpLocation').value, 'BIN-01');
nodes.get('receptionNpLocation').value = 'BIN-02';
qty('4'); await w.save();
assert.equal(JSON.parse(calls[0].options.body).count_location, 'BIN-02');
assert.equal(nodes.get('count-location-11').value, 'BIN-02');
assert.equal(nodes.get('count-location-11').defaultValue, 'BIN-02');
assert.equal(nodes.get('count-location-12').value, 'UNSAVED');
assert.equal(nodes.get('qty-12').value, '5');
""")

    def test_failed_location_save_keeps_scanner_and_legacy_drafts(self):
        self.run_js(r"""
mount('<input id="qty-11" type="number" value="9"><input id="reason-11" value="draft">' +
  '<input id="count-location-11" value="BIN-01"><td id="diff-11"></td>');
scan(); qty('4'); nodes.get('receptionNpLocation').value = '';
request = async () => ({ok: false, json: async () => ({error: 'Controlled failure'})});
await w.save();
assert.equal(JSON.parse(calls[0].options.body).count_location, '');
assert.equal(nodes.get('receptionNpLocation').value, '');
assert.equal(nodes.get('count-location-11').value, 'BIN-01');
assert.equal(nodes.get('receptionNpQuantity').value, '4');
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
scan(); assert.equal(nodes.get('receptionNpQuantity').value, '9');
assert.equal(calls.length, 0);
first.attention_planned_qty=2.5;
mount(cells(first, shipment.app_status));
assert.equal(nodes.get('qty-11').value, '');
scan();assert.equal(nodes.get('receptionNpQuantity').value, '');
await w.save();assert.equal(calls.length,0);
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
assert(notices.at(-1)[0].includes('El NP se guardó'));
assert(!nodes.get('receptionNpSave').disabled);
""")


if __name__ == '__main__':
    unittest.main()
