"""Frozen syntax anchors of the legacy variant's documentary overlay.

This fixture is parsed, not executed. It must not track new reader business rules.
"""


def import_reception_workbook(connection, workbook, filename, username, role):
    for records in workbook:
        if _source_confirms_arrival(records):
            record_arrival(connection, records)
    assign_demo_truck_guides(connection)


def _refresh_accounting_summary(connection, shipment_id, username, filename):
    expected_qty = 1
    received_qty = 0
    if (
            expected_qty > 0
            and received_qty == 0
    ):
        initialize_quantities(connection)
    new_accounting_status = 'PENDIENTE EM'
    old_app_status = 'CERRADO'
    if (
        new_accounting_status == "EM REGISTRADA"
        and old_app_status != 'CERRADO'
    ):
        close_shipment(connection)
    elif new_accounting_status != "EM REGISTRADA" and old_app_status == "CERRADO":
        reopen_shipment(connection)


def notify_importations(connection):
    _enqueue_notification(
        connection,
        "TRITON_IMPORTACIONES_EMAILS",
                "",
    )


def notify_accounting(connection):
    _enqueue_notification(
        connection,
        "TRITON_CONTABILIDAD_EMAILS",
                "",
    )
