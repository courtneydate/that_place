"""Management command: load_reference_data

Seeds the feeds app with:
  1. AEMO NEM Summary FeedProvider (system scope, no auth)
  2. network-tariffs ReferenceDataset (has_time_of_use, has_version)
  3. co2-factors ReferenceDataset (flat lookup, has_version)

Optionally imports rows from a CSV file into a named dataset:

    python manage.py load_reference_data --csv network-tariffs /path/to/tariffs.csv

CSV format must match the dataset's dimension_schema + value_schema columns, plus
the following optional TOU/validity columns (all may be blank):

    version, applicable_days, time_from, time_to, valid_from, valid_to

Row identity (for upsert) is: version + dimensions (all dimension_schema keys).
Existing rows with matching identity are updated; new rows are created.

Ref: SPEC.md § Feature: Feed Providers, § Feature: Reference Datasets
"""
import csv
import logging
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed data definitions
# ---------------------------------------------------------------------------

AEMO_PROVIDER = {
    'slug': 'aemo-nem-summary',
    'name': 'AEMO NEM Summary',
    'description': (
        'Australian Energy Market Operator — 5-minute electricity spot prices '
        'and generation mix for all NEM regions (QLD, NSW, VIC, SA, TAS).'
    ),
    'scope': 'system',
    'base_url': 'https://visualisations.aemo.com.au',
    'auth_type': 'none',
    'auth_param_schema': {},
    'poll_interval_seconds': 300,  # 5 minutes — matches AEMO dispatch interval
    'is_active': True,
    'endpoints': [
        {
            'path': '/aemo/apps/api/report/ELEC_NEM_SUMMARY',
            'method': 'GET',
            'response_root_jsonpath': '$.ELEC_NEM_SUMMARY[*]',
            'dimension_key': 'REGIONID',
            'channels': [
                {
                    'key': 'spot_price',
                    'label': 'Spot Price',
                    'unit': '$/MWh',
                    'data_type': 'numeric',
                    'value_jsonpath': '$.PRICE',
                },
                {
                    'key': 'total_demand',
                    'label': 'Total Demand',
                    'unit': 'MW',
                    'data_type': 'numeric',
                    'value_jsonpath': '$.TOTALDEMAND',
                },
                {
                    'key': 'net_interchange',
                    'label': 'Net Interchange',
                    'unit': 'MW',
                    'data_type': 'numeric',
                    'value_jsonpath': '$.NETINTERCHANGE',
                },
                {
                    'key': 'scheduled_generation',
                    'label': 'Scheduled Generation',
                    'unit': 'MW',
                    'data_type': 'numeric',
                    'value_jsonpath': '$.SCHEDULEDGENERATION',
                },
            ],
        },
    ],
}

NETWORK_TARIFFS_DATASET = {
    'slug': 'network-tariffs',
    'name': 'Network Tariffs (NEM)',
    'description': (
        'Annual electricity network tariffs (use-of-system charges) for all '
        'Australian NEM DNSPs. Supports time-of-use pricing. Updated annually '
        'each financial year (version format: "2025-26").'
    ),
    'scope': 'system',
    'dimension_schema': {
        'state': {'type': 'string', 'label': 'State', 'example': 'QLD'},
        'dnsp': {'type': 'string', 'label': 'DNSP', 'example': 'Energex'},
        'tariff_type': {
            'type': 'string',
            'label': 'Tariff Type',
            'example': 'residential_flat',
            'options': [
                'residential_flat',
                'residential_tou',
                'small_business_flat',
                'small_business_tou',
                'large_business_tou',
            ],
        },
        'voltage_level': {
            'type': 'string',
            'label': 'Voltage Level',
            'example': 'LV',
            'options': ['LV', 'HV', 'EHV'],
        },
    },
    'value_schema': {
        'rate_cents_per_kwh': {
            'type': 'numeric',
            'label': 'Energy Rate',
            'unit': 'c/kWh',
        },
        'daily_supply_charge_cents': {
            'type': 'numeric',
            'label': 'Daily Supply Charge',
            'unit': 'c/day',
        },
        'capacity_charge_cents_per_kva': {
            'type': 'numeric',
            'label': 'Capacity Charge (HV/commercial)',
            'unit': 'c/kVA/day',
        },
    },
    'has_time_of_use': True,
    'has_version': True,
}

CO2_FACTORS_DATASET = {
    'slug': 'co2-factors',
    'name': 'CO2 Emission Factors',
    'description': (
        'Scope 2 CO2-equivalent emission factors for grid electricity by '
        'NEM region. Source: Australian National Greenhouse Accounts (DCCEW). '
        'Updated annually (version format: "2024-25").'
    ),
    'scope': 'system',
    'dimension_schema': {
        'state': {'type': 'string', 'label': 'State / Region', 'example': 'QLD'},
        'grid': {
            'type': 'string',
            'label': 'Grid',
            'example': 'NEM',
            'options': ['NEM', 'WEM', 'SWIS'],
        },
    },
    'value_schema': {
        'kg_co2e_per_kwh': {
            'type': 'numeric',
            'label': 'Emission Factor',
            'unit': 'kg CO2-e/kWh',
        },
    },
    'has_time_of_use': False,
    'has_version': True,
}

# Seed rows for co2-factors (2023-24 NGAC factors, NEM regions)
# Source: Australian National Greenhouse Accounts Factor and Methods Workbook 2024
CO2_SEED_ROWS = [
    {'version': '2023-24', 'state': 'QLD', 'grid': 'NEM', 'kg_co2e_per_kwh': 0.79},
    {'version': '2023-24', 'state': 'NSW', 'grid': 'NEM', 'kg_co2e_per_kwh': 0.73},
    {'version': '2023-24', 'state': 'VIC', 'grid': 'NEM', 'kg_co2e_per_kwh': 0.90},
    {'version': '2023-24', 'state': 'SA',  'grid': 'NEM', 'kg_co2e_per_kwh': 0.43},
    {'version': '2023-24', 'state': 'TAS', 'grid': 'NEM', 'kg_co2e_per_kwh': 0.20},
    {'version': '2023-24', 'state': 'WA',  'grid': 'WEM', 'kg_co2e_per_kwh': 0.69},
]


class Command(BaseCommand):
    """Seed reference data: AEMO provider, network-tariffs and co2-factors datasets."""

    help = (
        'Seed reference data (AEMO FeedProvider, network-tariffs and co2-factors '
        'ReferenceDatasets). Optionally import rows from a CSV file.'
    )

    def add_arguments(self, parser):
        """Define optional --csv argument for importing tariff rows."""
        parser.add_argument(
            '--csv',
            nargs=2,
            metavar=('DATASET_SLUG', 'CSV_PATH'),
            help='Import rows into DATASET_SLUG from CSV_PATH (upsert).',
        )

    def handle(self, *args, **options):
        """Run the seed command."""
        self._seed_aemo_provider()
        self._seed_dataset(NETWORK_TARIFFS_DATASET)
        dataset = self._seed_dataset(CO2_FACTORS_DATASET)
        self._seed_co2_rows(dataset)

        if options['csv']:
            dataset_slug, csv_path = options['csv']
            self._import_csv(dataset_slug, csv_path)

        self.stdout.write(self.style.SUCCESS('Reference data seed complete.'))

    # -------------------------------------------------------------------------
    # Provider seed
    # -------------------------------------------------------------------------

    def _seed_aemo_provider(self) -> None:
        """Create or update the AEMO NEM Summary FeedProvider."""
        from apps.feeds.models import FeedProvider

        obj, created = FeedProvider.objects.update_or_create(
            slug=AEMO_PROVIDER['slug'],
            defaults={k: v for k, v in AEMO_PROVIDER.items() if k != 'slug'},
        )
        verb = 'Created' if created else 'Updated'
        self.stdout.write(f'{verb} FeedProvider: {obj.name}')

    # -------------------------------------------------------------------------
    # Dataset seed
    # -------------------------------------------------------------------------

    def _seed_dataset(self, defn: dict):
        """Create or update a ReferenceDataset from a definition dict."""
        from apps.feeds.models import ReferenceDataset

        obj, created = ReferenceDataset.objects.update_or_create(
            slug=defn['slug'],
            defaults={k: v for k, v in defn.items() if k != 'slug'},
        )
        verb = 'Created' if created else 'Updated'
        self.stdout.write(f'{verb} ReferenceDataset: {obj.name}')
        return obj

    # -------------------------------------------------------------------------
    # CO2 rows seed
    # -------------------------------------------------------------------------

    def _seed_co2_rows(self, dataset) -> None:
        """Seed CO2 emission factor rows (idempotent)."""
        from apps.feeds.models import ReferenceDatasetRow

        dimension_keys = list(CO2_FACTORS_DATASET['dimension_schema'].keys())
        value_keys = list(CO2_FACTORS_DATASET['value_schema'].keys())
        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for row_data in CO2_SEED_ROWS:
                version = row_data['version']
                dimensions = {k: row_data[k] for k in dimension_keys}
                values = {k: row_data[k] for k in value_keys}

                _, created = ReferenceDatasetRow.objects.update_or_create(
                    dataset=dataset,
                    version=version,
                    dimensions=dimensions,
                    defaults={
                        'values': values,
                        'is_active': True,
                    },
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            f'CO2 factors: {created_count} created, {updated_count} updated.'
        )

    # -------------------------------------------------------------------------
    # CSV import
    # -------------------------------------------------------------------------

    def _import_csv(self, dataset_slug: str, csv_path: str) -> None:
        """Import rows from a CSV file into the named dataset (upsert).

        Expected CSV columns:
          - All dimension_schema keys (required)
          - All value_schema keys (required, numeric)
          - version           (optional — required if dataset has_version=True)
          - applicable_days   (optional — comma-separated ints, e.g. "0,1,2,3,4")
          - time_from         (optional — HH:MM)
          - time_to           (optional — HH:MM)
          - valid_from        (optional — YYYY-MM-DD)
          - valid_to          (optional — YYYY-MM-DD)

        Row identity for upsert: version + all dimension_schema keys.
        """
        from apps.feeds.models import ReferenceDataset, ReferenceDatasetRow

        try:
            dataset = ReferenceDataset.objects.get(slug=dataset_slug)
        except ReferenceDataset.DoesNotExist:
            raise CommandError(f'ReferenceDataset with slug "{dataset_slug}" not found.')

        path = Path(csv_path)
        if not path.exists():
            raise CommandError(f'CSV file not found: {csv_path}')

        dimension_keys = list(dataset.dimension_schema.keys())
        value_keys = list(dataset.value_schema.keys())

        created_count = 0
        updated_count = 0
        error_count = 0

        with open(path, newline='', encoding='utf-8-sig') as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)

        with transaction.atomic():
            for i, row in enumerate(rows, start=2):  # start=2: row 1 is header
                try:
                    version = row.get('version', '').strip() or None
                    if dataset.has_version and not version:
                        raise ValueError('version is required for this dataset.')

                    dimensions = {}
                    for key in dimension_keys:
                        val = row.get(key, '').strip()
                        if not val:
                            raise ValueError(f'Dimension "{key}" is missing.')
                        dimensions[key] = val

                    values = {}
                    for key in value_keys:
                        raw = row.get(key, '').strip()
                        if raw:
                            try:
                                values[key] = float(raw)
                            except ValueError:
                                raise ValueError(
                                    f'Value "{key}" = "{raw}" is not a valid number.'
                                )

                    # TOU fields
                    applicable_days = None
                    days_raw = row.get('applicable_days', '').strip()
                    if days_raw:
                        applicable_days = [int(d.strip()) for d in days_raw.split(',') if d.strip()]

                    time_from = row.get('time_from', '').strip() or None
                    time_to = row.get('time_to', '').strip() or None

                    valid_from = None
                    valid_from_raw = row.get('valid_from', '').strip()
                    if valid_from_raw:
                        valid_from = date.fromisoformat(valid_from_raw)

                    valid_to = None
                    valid_to_raw = row.get('valid_to', '').strip()
                    if valid_to_raw:
                        valid_to = date.fromisoformat(valid_to_raw)

                    _, created = ReferenceDatasetRow.objects.update_or_create(
                        dataset=dataset,
                        version=version,
                        dimensions=dimensions,
                        defaults={
                            'values': values,
                            'applicable_days': applicable_days,
                            'time_from': time_from,
                            'time_to': time_to,
                            'valid_from': valid_from,
                            'valid_to': valid_to,
                            'is_active': True,
                        },
                    )
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1

                except Exception as exc:
                    self.stderr.write(f'  Row {i}: {exc}')
                    error_count += 1

        self.stdout.write(
            f'{dataset.name} CSV import: '
            f'{created_count} created, {updated_count} updated, {error_count} errors.'
        )
        if error_count:
            raise CommandError(f'{error_count} row(s) failed — see errors above.')
