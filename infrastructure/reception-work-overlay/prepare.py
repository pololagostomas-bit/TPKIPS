"""Install only the reception work projection on an approved variant image."""
import ast
import re
import sys
from pathlib import Path

IMPORT = 'from backend.services.reception_work import reception_work_report\n'
CLOSURE_IMPORT = 'from backend.services.reception_closure import reconcile_closure\n'
ROUTE = '''        if parsed.path == "/api/receptions/work":
            try:
                username, role = current_user(self)
                query = parse_qs(parsed.query)
                with db() as connection:
                    payload = reception_work_report(connection, username, role,
                        include_history=query.get('history',['0'])[0]=='1',
                        search=query.get('search',[''])[0],stage=query.get('stage',[''])[0],
                        sla=query.get('sla',[''])[0],limit=query.get('limit',['100'])[0],
                        offset=query.get('offset',['0'])[0])
                self.send_json(payload)
            except PermissionError as error:
                self.send_json({'error':str(error)},403)
            except (ValueError,TypeError):
                self.send_json({'error':'Selecciona una pagina valida'},400)
            return
'''
SUMMARY = '''    if module == "reception":
        with db() as connection:
            return reception_work_report(connection, username, role)['summary']
'''
ASSETS = '''<link rel="stylesheet" href="/assets/reception-work.css?v=20261011-1">
<script src="/assets/reception-work.js?v=20261011-1"></script>
'''


def once(source, old, new, label):
    if source.count(old) != 1:
        raise ValueError('Approved base changed; review ' + label)
    return source.replace(old, new, 1)


def transform_function(source, name, transform, parent=None):
    tree = ast.parse(source)
    scope = tree if parent is None else next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == parent), None)
    nodes = [node for node in (scope.body if scope else [])
             if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(nodes) != 1:
        raise ValueError('Missing unique function: ' + name)
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    block = ''.join(lines[node.lineno-1:node.end_lineno])
    lines[node.lineno-1:node.end_lineno] = [transform(block)]
    result = ''.join(lines)
    ast.parse(result)
    return result


def patch_accounting(source):
    def patch(block):
        function = ast.parse(block).body[0]
        if any(arg.arg == 'include_unreceived_ips' for arg in function.args.args):
            legacy = block.count('if received_ips and not include_unreceived_ips:') == 1
            nested = (block.count('    if not include_unreceived_ips:\n        received_ips = set()') == 1
                      and block.count('        if received_ips:\n            expected_ips = expected_ips.intersection(received_ips)') == 1)
            if not (legacy or nested):
                raise ValueError('Incomplete full-IP accounting guard')
            return block
        block = once(block,
            'def _accounting_status_for_shipment(connection, shipment_id, shipment=None, rows=None):',
            'def _accounting_status_for_shipment(connection, shipment_id, shipment=None, rows=None,\n'
            '                                  include_unreceived_ips=False):', 'accounting signature')
        return once(block, '    if received_ips:',
                    '    if received_ips and not include_unreceived_ips:', 'accounting scope')
    return transform_function(source, '_accounting_status_for_shipment', patch)


def patch_app(source):
    if IMPORT not in source:
        source = once(source, 'from backend.services import identity\n',
                      'from backend.services import identity\n' + IMPORT, 'work import')
    elif source.count(IMPORT) != 1:
        raise ValueError('Duplicate work import')

    def summary(block):
        if 'reception_work_report(' in block:
            if block.count("return reception_work_report(connection, username, role)['summary']") != 1:
                raise ValueError('Unknown work summary integration')
            return block
        return once(block, '    username_key = text(username).strip().lower()\n',
                    SUMMARY + '    username_key = text(username).strip().lower()\n', 'work summary')
    source = transform_function(source, 'work_summary', summary)

    def handler(block):
        if '/api/receptions/work' in block:
            if block.count(ROUTE.rstrip()) != 1:
                raise ValueError('Unknown work route integration')
        else:
            block = once(block, '        if parsed.path == "/api/receptions":',
                         ROUTE + '        if parsed.path == "/api/receptions":', 'work GET route')
        if "'/assets/reception-work.js'" not in block:
            block = once(block, "'/assets/mobile-workspace.js'",
                         "'/assets/reception-work.js', '/assets/reception-work.css', '/assets/mobile-workspace.js'",
                         'static asset allowlist')
        elif block.count("'/assets/reception-work.js'") != 1 or block.count("'/assets/reception-work.css'") != 1:
            raise ValueError('Incomplete work asset allowlist')
        return block
    source = transform_function(source, 'do_GET', handler, parent='Handler')
    if CLOSURE_IMPORT not in source:
        source = once(source, IMPORT, IMPORT+CLOSURE_IMPORT, 'closure import')
    def post(block):
        if '/reconcile-closure' in block:
            if block.count('payload = reconcile_closure(connection, shipment_id, data, username, role)') != 1:
                raise ValueError('Unknown closure integration')
            return block
        return once(block, '                    if parsed.path.endswith("/receipts"):',
            '                    if parsed.path.endswith("/reconcile-closure"):\n'
            '                        connection.execute("BEGIN IMMEDIATE")\n'
            '                        payload = reconcile_closure(connection, shipment_id, data, username, role)\n'
            '                    elif parsed.path.endswith("/receipts"):', 'closure POST')
    return transform_function(source, 'do_POST', post, parent='Handler')


def patch_lifecycle(source):
    source = patch_accounting(source)
    def sla(block):
        if 'from backend.services.reception_sla import elapsed_hours' in block:
            return block
        if 'cursor.weekday() != 6' not in block:
            raise ValueError('Unknown approved SLA rule')
        return '''def _elapsed_hours_excluding_sundays(start_value, end_value=None):
    """Compatibility entry point: exclude Sundays AND national holidays."""
    from backend.services.reception_sla import elapsed_hours
    return elapsed_hours(start_value, end_value or reception_now())'''
    source = transform_function(source, '_elapsed_hours_excluding_sundays', sla)
    def accounting(block):
        if 'and closure_check(connection, shipment_id)[0]' in block:
            return block
        signature = block.splitlines(keepends=True)[0]
        anchor = ('    from backend.services.cloud_import_policy import documentary_only\n'
                  if 'def _refresh_accounting_summary(' in signature else signature)
        block = once(block, anchor, anchor+'    from backend.services.reception_closure import closure_check\n',
                     'accounting closure import')
        return once(block, '        and _all_expected_ips_received(connection, shipment_id, shipment)\n',
            '        and _all_expected_ips_received(connection, shipment_id, shipment)\n'
            '        and closure_check(connection, shipment_id)[0]\n', 'accounting closure guard')
    for name in ('_refresh_accounting_summary', '_refresh_manual_accounting_status'):
        source = transform_function(source, name, accounting)
    def transition(block):
        if 'primary_status, primary_condition = master_state(connection, shipment_id)' in block:
            return block
        anchor = '        primary_condition = primary_attention["condition_status"] if primary_attention else condition\n'
        return once(block, anchor, anchor+
            '        if new_status == "CERRADO":\n'
            '            from backend.services.reception_closure import master_state\n'
            '            primary_status, primary_condition = master_state(connection, shipment_id)\n'
            '            shipment_status = primary_status\n', 'partial master closure')
    return transform_function(source, 'change_reception_status', transition)


def patch_resolver(source):
    def resolver(block):
        if 'BL no encontrada en la base de Importaciones.' in block:
            if 'INSERT INTO reception_shipments' in block:
                raise ValueError('Partial known-only BL rule')
            return block
        if ('INSERT INTO reception_shipments' not in block or
                'return matches[0], False' not in block):
            raise ValueError('Unknown BL resolver base')
        anchor = ('    if not create_if_missing:' if '    if not create_if_missing:' in block
                  else '    timestamp = reception.reception_now()')
        if block.count(anchor) != 1:
            raise ValueError('Unknown provisional BL integration')
        block = block[:block.index(anchor)] + (
            '    raise ValueError("BL no encontrada en la base de Importaciones. Actualiza el corte o solicita su registro al administrador")')
        return block.replace('La BL ya esta cerrada y no puede recibirse nuevamente',
            'La BL ya esta cerrada; el administrador debe reabrirla antes de otro arribo')
    return transform_function(source, 'resolve_entered_bl', resolver)


def patch_template(source):
    if '/assets/reception-work.' in source:
        if source.count('/assets/reception-work.js') != 1 or source.count('/assets/reception-work.css') != 1:
            raise ValueError('Incomplete reception work assets')
        if source.index('/assets/reception-work.js') > source.index('/assets/workspace-shell.js'):
            raise ValueError('Work module must load before workspace navigation')
        return source
    anchors = list(re.finditer(r'<script src="/assets/workspace-shell\.js[^"\n]*">', source))
    if len(anchors) != 1:
        raise ValueError('Missing unique workspace script')
    index = anchors[0].start()
    return source[:index] + ASSETS + source[index:]


def main(root):
    targets = [('backend/app.py', patch_app),
               ('backend/services/reception.py', patch_lifecycle),
               ('backend/services/truck_entry.py', patch_resolver),
               ('frontend/templates/reception.html', patch_template)]
    results = [(root / path, transform((root / path).read_text(encoding='utf-8')))
               for path, transform in targets]
    for path, result in results:
        path.write_text(result, encoding='utf-8')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
