"""Apply the reviewed documentary guards without replacing a variant's app."""
import ast
import sys
from pathlib import Path


RECEPTION_CHANGES = {
    'import_reception_workbook': [
        ('        if _source_confirms_arrival(records):',
         '        from backend.services.cloud_import_policy import documentary_only\n'
         '        if not documentary_only.get() and _source_confirms_arrival(records):'),
        ('    assign_demo_truck_guides(connection)',
         '    from backend.services.cloud_import_policy import documentary_only\n'
         '    if not documentary_only.get():\n        assign_demo_truck_guides(connection)')],
    '_refresh_accounting_summary': [
        ('def _refresh_accounting_summary(connection, shipment_id, username, filename):',
         'def _refresh_accounting_summary(connection, shipment_id, username, filename):\n'
         '    from backend.services.cloud_import_policy import documentary_only'),
        ('            expected_qty > 0',
         '            not documentary_only.get()\n            and expected_qty > 0'),
        ('        new_accounting_status == "EM REGISTRADA"',
         '        not documentary_only.get()\n        and new_accounting_status == "EM REGISTRADA"'),
        ('    elif new_accounting_status != "EM REGISTRADA" and old_app_status == "CERRADO":',
         '    elif not documentary_only.get() and new_accounting_status != "EM REGISTRADA" and old_app_status == "CERRADO":')]
}

CONNECT_FUNCTION = """  function installCloudConnection(){
    const actions=dialog.querySelector('.daily-cloud-actions');
    if(!actions || role()!=='ADMINISTRADOR')return;
    const button=document.createElement('button');
    button.id='dailyCloudConnect'; button.type='button'; button.className='primary';
    button.textContent='Conectar con Microsoft';
    button.addEventListener('click',()=>location.assign('/cloud-connection'));
    actions.prepend(button);
  }
"""
TOOLBAR_CHANGES = [
    ('  function openDataV2(){', CONNECT_FUNCTION + '  function openDataV2(){'),
    (");el('dailyCloudSync')?.addEventListener",
     ");installCloudConnection();el('dailyCloudSync')?.addEventListener")]

LEGACY_BUTTON = "  const microsoftButton=document.createElement('button'); microsoftButton.type='button'; microsoftButton.textContent='Microsoft 365'; microsoftButton.hidden=true; microsoftButton.onclick=()=>{location.href='/cloud-connection';}; toolbar?.append(microsoftButton);\n"
LEGACY_LINES = [LEGACY_BUTTON, LEGACY_BUTTON.replace('microsoftButton=', 'microsoftButton = '),
                '      microsoftButton.hidden = !admin;\n', ' microsoftButton.hidden = !admin;']

STYLE_CHANGE = (
    '.daily-dialog::backdrop{background:#17232b88}.daily-dialog *{box-sizing:border-box}',
    '.daily-dialog::backdrop{background:#17232b88}.daily-dialog *{box-sizing:border-box}\n'
    '.daily-cloud-actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:16px 0}.daily-cloud-actions small{flex-basis:100%}')


def replace_once(source, changes, label):
    installed = [new in source for _, new in changes]
    if all(installed):
        if any(source.count(new) != 1 for _, new in changes):
            raise ValueError('Duplicate cloud guards: ' + label)
        return source
    if any(installed):
        raise ValueError('Partial cloud patch; review before building: ' + label)
    for old, new in changes:
        if source.count(old) != 1:
            raise ValueError('Approved base changed; review before building: ' + label)
        source = source.replace(old, new)
    return source


def patch_reception(source):
    lines = source.splitlines(keepends=True)
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name in RECEPTION_CHANGES]
    if len(nodes) != len(RECEPTION_CHANGES):
        raise ValueError('Missing reception import functions')
    for node in sorted(nodes, key=lambda value: value.lineno, reverse=True):
        block = ''.join(lines[node.lineno - 1:node.end_lineno])
        lines[node.lineno - 1:node.end_lineno] = [
            replace_once(block, RECEPTION_CHANGES[node.name], node.name)]
    result = ''.join(lines)
    return redact_notification_defaults(result)


def redact_notification_defaults(source):
    lines = source.splitlines(keepends=True)
    arguments = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == '_enqueue_notification' and len(node.args) >= 2
                and isinstance(node.args[-2], ast.Constant)
                and node.args[-2].value in {'TRITON_IMPORTACIONES_EMAILS', 'TRITON_CONTABILIDAD_EMAILS'}):
            argument = node.args[-1]
            if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str) or argument.lineno != argument.end_lineno:
                raise ValueError('Unexpected notification default; review before building')
            arguments.append(argument)
    if len(arguments) != 2:
        raise ValueError('Unexpected notification configuration points')
    for argument in sorted(arguments, key=lambda node: node.lineno, reverse=True):
        line = lines[argument.lineno - 1].encode('utf-8')
        lines[argument.lineno - 1] = (line[:argument.col_offset] + b'""' + line[argument.end_col_offset:]).decode('utf-8')
    result = ''.join(lines)
    ast.parse(result)
    return result


def patch_toolbar(source):
    for legacy in LEGACY_LINES:
        source = source.replace(legacy, '')
    if 'microsoftButton' in source:
        raise ValueError('Unknown legacy Microsoft button; review before building')
    return replace_once(source, TOOLBAR_CHANGES, 'daily-work.js')


def patch_workspace(source):
    old = "      action(tools,'Correos','Consultar solicitudes y estado de envío',()=>window.showNotifications());"
    new = old + "\n      action(tools,'Alertas de compras / OC','Pendientes y reportes de Importaciones',()=>location.assign('/purchase-alerts'));"
    return replace_once(source, [(old, new)], 'workspace-shell.js')


def main(root):
    paths = [root / 'backend/services/reception.py', root / 'frontend/static/daily-work.js',
             root / 'frontend/static/daily-work.css', root / 'frontend/static/workspace-shell.js']
    # Validate all files before touching any; a changed base aborts the build.
    results = [patch_reception(paths[0].read_text(encoding='utf-8')),
               patch_toolbar(paths[1].read_text(encoding='utf-8')),
               replace_once(paths[2].read_text(encoding='utf-8'), [STYLE_CHANGE], 'daily-work.css'),
               patch_workspace(paths[3].read_text(encoding='utf-8'))]
    for path, result in zip(paths, results):
        path.write_text(result, encoding='utf-8')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
