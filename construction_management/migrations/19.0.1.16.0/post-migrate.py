"""Construction Management 19.0.1.16.0: projects already started keep their BOQ locked."""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE construction_project p SET was_started = TRUE
         WHERE p.state NOT IN ('draft', 'cancelled')
            OR EXISTS (SELECT 1 FROM construction_boq_history h WHERE h.project_id = p.id)
            OR EXISTS (SELECT 1 FROM construction_owner_invoice i WHERE i.project_id = p.id)
            OR EXISTS (SELECT 1 FROM construction_material_request r WHERE r.project_id = p.id)
    """)
