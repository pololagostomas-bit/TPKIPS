"""Install only the reception work projection on an approved variant image."""
import ast
import re
import sys
from pathlib import Path

IMPORT = 'from backend.services.reception_work import reception_work_report\n'
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
            if block.count('if received_ips and not include_unreceived_ips:') != 1:
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
    return transform_function(source, 'do_GET', handler, parent='Handler')


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
               ('backend/services/reception.py', patch_accounting),
               ('frontend/templates/reception.html', patch_template)]
    results = [(root / path, transform((root / path).read_text(encoding='utf-8')))
               for path, transform in targets]
    for path, result in results:
        path.write_text(result, encoding='utf-8')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
