"""Construction fleet construction driver document support."""

from odoo import fields, models


class ConstructionDriverDocument(models.Model):
    """Construction Driver Document."""

    _name = 'construction.driver.document'
    _description = 'Driver Document'
    _order = 'driver_id, document_type, id'
    driver_id = fields.Many2one(
        'construction.driver', string='Driver', required=True, ondelete='cascade', index=True
    )
    company_id = fields.Many2one(related='driver_id.company_id', store=True, string='Company')
    document_type = fields.Selection(
        [
            ('license', 'Driving License Copy'),
            ('national_id', 'National ID / Iqama Copy'),
            ('work_permit', 'Work Permit'),
            ('health_certificate', 'Health Certificate'),
            ('other', 'Other'),
        ],
        string='Document Type',
        required=True,
        default='license',
    )
    name = fields.Char(string='Description')
    number = fields.Char(string='Document Number')
    issue_date = fields.Date(string='Issue Date')
    expiry_date = fields.Date(string='Expiry Date')
    attachment = fields.Binary(string='Copy', attachment=True, required=True)
    attachment_name = fields.Char(string='File Name')
