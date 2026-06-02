"""Sprint 32 — Invoice PDF Templates, BillingInvoice, void_reason on BillingRun."""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_tenant_gst_rate_tenant_invoice_number_format_and_more'),
        ('billing', '0002_sprint31_runs'),
    ]

    operations = [
        # InvoicePDFTemplate
        migrations.CreateModel(
            name='InvoicePDFTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tenant', models.ForeignKey(
                    blank=True,
                    help_text='Null = platform-wide default (accessible to all tenants).',
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='invoice_pdf_templates',
                    to='accounts.tenant',
                )),
                ('name', models.CharField(max_length=120)),
                ('html_content', models.TextField(
                    help_text='Full HTML/CSS template rendered by WeasyPrint. May use Django template tags.',
                )),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['name']},
        ),

        # void_reason on BillingRun
        migrations.AddField(
            model_name='billingrun',
            name='void_reason',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Operator-supplied reason captured when the run is voided (Sprint 32).',
            ),
        ),

        # BillingInvoice
        migrations.CreateModel(
            name='BillingInvoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('billing_run', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='invoices',
                    to='billing.billingrun',
                )),
                ('billing_account', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='invoices',
                    to='billing.billingaccount',
                )),
                ('invoice_number', models.CharField(
                    help_text='Formatted per Tenant.invoice_number_format; unique per tenant.',
                    max_length=120,
                )),
                ('period_start', models.DateTimeField()),
                ('period_end', models.DateTimeField()),
                ('subtotal_cents', models.IntegerField(default=0)),
                ('gst_cents', models.IntegerField(default=0)),
                ('total_cents', models.IntegerField(default=0)),
                ('pdf_object_key', models.CharField(
                    blank=True,
                    default='',
                    help_text='S3/MinIO object key where the PDF is stored.',
                    max_length=500,
                )),
                ('status', models.CharField(
                    choices=[('draft', 'Draft'), ('delivered', 'Delivered'), ('void', 'Void')],
                    default='draft',
                    max_length=20,
                )),
                ('delivery_status', models.CharField(
                    choices=[
                        ('pending', 'Pending'),
                        ('sent', 'Sent'),
                        ('delivered', 'Delivered (receipt confirmed)'),
                        ('failed', 'Failed'),
                    ],
                    default='pending',
                    max_length=20,
                )),
                ('issued_at', models.DateTimeField(
                    auto_now_add=True,
                    help_text='When the invoice record was created (at run finalize).',
                )),
                ('delivered_at', models.DateTimeField(
                    blank=True,
                    null=True,
                    help_text='When the first successful email send completed.',
                )),
                ('voided_at', models.DateTimeField(
                    blank=True,
                    null=True,
                    help_text='When the parent run was voided.',
                )),
            ],
            options={'ordering': ['-issued_at']},
        ),
        migrations.AddConstraint(
            model_name='billinginvoice',
            constraint=models.UniqueConstraint(
                fields=['billing_run', 'billing_account'],
                name='billing_invoice_unique_per_run_account',
            ),
        ),
        migrations.AddIndex(
            model_name='billinginvoice',
            index=models.Index(fields=['billing_run', 'billing_account'], name='billing_inv_billing_idx'),
        ),
    ]
