import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InlineScriptCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self._current = None

    def handle_starttag(self, tag, attrs):
        if tag == "script" and not dict(attrs).get("src"):
            self._current = []

    def handle_data(self, data):
        if self._current is not None:
            self._current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._current is not None:
            self.scripts.append("".join(self._current))
            self._current = None


@unittest.skipUnless(shutil.which("node"), "Node.js is needed to syntax-check browser scripts")
class ReceptionTemplateSyntaxTests(unittest.TestCase):
    def test_cancelled_scanner_guide_can_be_removed_from_history_by_admin(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn("'FINALIZADA','CANCELADA'].includes(status)", template)
        self.assertIn("'CANCELADA':'CANCELADA'", template)
        self.assertIn("Retirar del historial", template)
        self.assertIn("archiveCancelledScanGuide('${esc(summary.truck_guide||'')}')", template)

    def test_attention_summary_shows_skus_received_vs_total_and_units(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        summary = next(line for line in template.splitlines() if line.startswith("     function attentionSummary(s){"))
        script = "\n".join((
            "const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('\\\"','&quot;');",
            "const stateLabel=value=>value;",
            summary.strip(),
            "const html=attentionSummary({attention_count:2,attentions:[{label:'Atención 1/2',app_status:'CERRADO',lines:[{np_code:'NP-1',planned_qty:5,verified_qty:3},{np_code:' np-1 ',planned_qty:4,verified_qty:0},{np_code:'NP-2',planned_qty:10,verified_qty:0}]},{label:'Atención 2/2',app_status:'INICIO CONTEO',lines:[{np_code:'NP-3',planned_qty:166,verified_qty:166}]}]});",
            "if(!html.includes('1 / 2</strong> SKU recibidos')||!html.includes('3 / 19</strong> unidades verificadas'))process.exit(1);",
            "if(!html.includes('1 / 1</strong> SKU recibidos')||!html.includes('166 / 166</strong> unidades verificadas'))process.exit(2);",
        ))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_reopened_em_stage_renders_existing_em_as_editable_for_assigned_worker(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        em_card = next(line for line in template.splitlines() if line.startswith("    function emEntryCard(s){"))
        script = "\n".join((
            "const states=['PROGRAMADO','ARRIBADO','REVISION SISTEMA','EM','UBICACION'];",
            "const userName=()=> 'worker';",
            "const isAdmin=()=>false;",
            "const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('\\\"','&quot;');",
            em_card.strip(),
            "const html=emEntryCard({app_status:'EM',attention_id:8,accounting_status:'EM REGISTRADA',current_assistant:'worker',lines:[{attention_verified_qty:1}],em_number:'EM-OLD',accounting_refs:[{id:4,fr_number:'FR-4',ip_reference:'IP-4',ip_reference_key:'IP-4',em_status:'EM COMPLETAS',em_eligible:1,pending_em_count:0,em_numbers:['EM-OLD'],em_entries:[{id:31,attention_id:8,em_number:'EM-OLD'}],linked_lines:[{np_code:'NP-4',description:'Pieza',ov_number:'OV-4',expected_qty:1,received_qty:1,pending_qty:0}]}]});",
            "if(!html.includes('data-em-id=\"31\"')||!html.includes('value=\"EM-OLD\"')||!html.includes('onclick=\"registerEmFromApp()\"'))process.exit(1);",
            "if(/onclick=\"registerEmFromApp\\(\\)\"[^>]*disabled/.test(html))process.exit(2);",
        ))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_admin_rewind_refreshes_the_open_detail_immediately(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn(
            "await mutate(shipmentUrl('/rewind'),{status,reason:reason.trim()});renderDetail();notify('Etapa reabierta para repetir el trabajo')",
            template,
        )

    def test_truck_tutorial_copy_respects_guidance_preference(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        tutorial_phrases = (
            "Tránsito agrupa las BL que podrían venir juntas",
            "Indica cuántos bultos llegaron para cada BL",
            "La llegada de bultos ya fue cerrada",
        )
        for phrase in tutorial_phrases:
            with self.subTest(phrase=phrase):
                position = template.index(phrase)
                opening_tag = template.rfind("<div", 0, position)
                self.assertIn("help-guidance", template[opening_tag:position])

    def test_truck_and_bl_workflows_have_separate_stage_numbering(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        truck_steps = ("0. EN TRÁNSITO", "1. LLEGADA", "2. ZONA RECEPCIÓN")
        bl_steps = (
            "0. ZONA DE RECEPCIÓN",
            "1. INICIO CONTEO",
            "2. EM (STICKER)",
            "3. UBICACIÓN",
            "4. VALIDACIÓN / TRANSFERENCIA",
            "5. TRANSFERENCIA SOLICITADA",
            "6. CERRADO",
        )
        for label in (*truck_steps, *bl_steps):
            with self.subTest(label=label):
                self.assertIn(label, template)
        self.assertIn("truckReceptionStates=['ARRIBADO','REVISION SISTEMA','EM','UBICACION','VALIDACION','SOLICITUD TRANSFERENCIA','CERRADO']", template)
        self.assertIn("function receptionStageIndex(status,shipment=selected)", template)

    def test_truck_confirmation_keeps_current_guide_and_admin_can_choose_prior_stage(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn("await refreshTruckGuideWorkspace(data)", template)
        self.assertIn("function refreshTruckGuideWorkspace(summary)", template)
        self.assertNotIn("eyebrow==='Control administrativo del tránsito')card.remove()", template)
        self.assertIn("const truckGuideRewindOptions=status=>", template)

    def test_truck_arrival_requires_start_click_but_start_is_not_persisted(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn("let arrivalStartedGuide=''", template)
        self.assertIn("function startTruckArrival()", template)
        self.assertIn("onclick=\"startTruckArrival()\">Iniciar llegada", template)
        self.assertIn("arrivalStartedGuide===guide?1:0", template)
        self.assertIn("arrivalStartedGuide!==String(summary.truck_guide", template)
        self.assertIn("status==='PENDIENTE'&&arrivalStartedGuide===guide?1:", template)

    def test_saving_truck_arrival_has_no_extra_browser_confirmation(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        start = template.index("async function saveTruckArrival(){")
        end = template.index("async function saveTruckLocations(){", start)
        handler = template[start:end]
        self.assertNotIn("confirm(", handler)
        self.assertIn("Guardar llegada y continuar", template)
        self.assertIn("await refreshTruckGuideWorkspace(data)", handler)

    def test_truck_linked_bl_exposes_independent_admin_rewind_controls(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn("Control administrativo de BL", template)
        self.assertIn("Control administrativo del camión", template)
        self.assertIn("onclick=\"rewindStage()\">Reabrir BL", template)
        self.assertIn("onclick=\"revertTruckGuide(", template)
        self.assertIn("currentGuideStatus!=='PENDIENTE'", template)
        self.assertIn("localStorage.removeItem(`triton-wms-jose-arrival:${guide}`)", template)

    def test_pending_truck_guide_remains_openable_from_linked_bl(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn("async function openTruckGuideFromBl(guide)", template)
        self.assertIn("El camión ya está en Tránsito. Puedes abrirlo", template)
        self.assertIn("onclick=\"openTruckGuideFromBl('", template)
        start = template.index("function adminRewindCard(s){")
        end = template.index("\n", start)
        admin_card = template[start:end]
        script = "\n".join((
            "const isAdmin=()=>true;",
            "const states=['PROGRAMADO','ARRIBADO','REVISION SISTEMA','EM','UBICACION','VALIDACION','SOLICITUD TRANSFERENCIA','CERRADO'];",
            "const stateLabel=value=>value;",
            "const esc=value=>String(value??'');",
            "const truckGuideRewindOptions=status=>String(status).toUpperCase()==='PENDIENTE'?'':'<option value=EN_CURSO>1. Llegada</option>';",
            admin_card,
            "const html=adminRewindCard({app_status:'PROGRAMADO',truck_guide:'PRUEBA-20260904-0542',guide_status:'PENDIENTE'});",
            "if(!html.includes('Abrir guía de camión')||!html.includes('openTruckGuideFromBl'))process.exit(1);",
        ))
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_truck_zone_defaults_location_quantity_to_received_bl_packages(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn("package_count:Number(bl.received_this_truck||0)", template)
        self.assertIn("type=\"number\" min=\"1\" step=\"1\" value=\"${packages===''?'':Number(packages)}\"", template)

    def test_final_np_locations_are_checked_by_default_while_editable(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn("${(editable||line.final_location_confirmed)?'checked':''}", template)

    def test_reception_stage_tabs_are_rendered_in_numeric_flow_order(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn(
            "const order=truck?['zona','admin','sistema','em','ubicacion','validacion','transferencia','fuente']",
            template,
        )
        self.assertIn(
            "const order=truck?['zona','admin','sistema','em','ubicacion','validacion','transferencia','fuente']:['bultos','zona','admin','sistema','em','ubicacion','validacion','transferencia','fuente']",
            template,
        )

    def test_completed_truck_exposes_received_bls_and_home_loads_reception_queue(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn("Abrir BL para conteo", template)
        self.assertIn("onclick=\"loadDetail(${truckRowId(bl)})\"", template)
        self.assertIn("await Promise.all([loadTruckGuides(),loadReceptions()])", template)

    def test_reception_guidance_respects_profile_toggle_but_fr_blocker_remains(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn('<div class="stage-guide help-guidance" role="status">', template)
        self.assertIn('<div class="notice help-guidance"><strong>Factura de reserva pendiente.', template)
        self.assertIn('<p class="help-guidance">Confirma después de completar y guardar esta etapa.</p>', template)
        self.assertIn('<div class="notice error"><strong>No se puede iniciar EM.</strong>', template)

    def test_existing_html5_qrcode_reader_is_connected_to_reception_inputs(self):
        template = (ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8")
        self.assertIn("https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js", template)
        for field, target in (
            ("scanTruckBlCode", "truck-bl"),
            ("scanTruckPackageCode", "truck-package"),
            ("scanReceptionNp", "reception-np"),
        ):
            with self.subTest(field=field):
                self.assertIn(f"['{field}','{target}'", template)
        self.assertIn("if(!window.isSecureContext)", template)
        self.assertIn("window.Html5Qrcode", template)

    def test_inline_scripts_parse_as_javascript(self):
        parser = InlineScriptCollector()
        parser.feed((ROOT / "frontend" / "templates" / "reception.html").read_text(encoding="utf-8"))
        scripts = [script for script in parser.scripts if script.strip()]
        self.assertTrue(scripts, "expected inline scripts in reception.html")

        for index, script in enumerate(scripts):
            with self.subTest(script=index):
                result = subprocess.run(
                    [shutil.which("node"), "-e", "new Function(require('fs').readFileSync(0, 'utf8'));"],
                    input=script,
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
