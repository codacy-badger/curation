import StringIO
import unittest
import os

from google.appengine.ext import testbed

import gcs_utils
import resources
from validation import export
from validation import achilles
from test_util import FAKE_HPO_ID
import test_util
import time
import bq_utils
import json

BQ_TIMEOUT_SECONDS = 5


class ExportTest(unittest.TestCase):
    def setUp(self):
        super(ExportTest, self).setUp()
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_app_identity_stub()
        self.testbed.init_memcache_stub()
        self.testbed.init_urlfetch_stub()
        self.testbed.init_blobstore_stub()
        self.testbed.init_datastore_v3_stub()
        self.hpo_bucket = gcs_utils.get_hpo_bucket(test_util.FAKE_HPO_ID)

    def _write_cloud_str(self, bucket, name, contents_str):
        fp = StringIO.StringIO(contents_str)
        return self._write_cloud_fp(bucket, name, fp)

    def _write_cloud_file(self, bucket, f):
        name = os.path.basename(f)
        with open(f, 'r') as fp:
            return self._write_cloud_fp(bucket, name, fp)

    def _write_cloud_fp(self, bucket, name, fp):
        return gcs_utils.upload_object(bucket, name, fp)

    def _populate_achilles(self):
        from google.appengine.api import app_identity

        app_id = app_identity.get_application_id()

        test_file_name = achilles.ACHILLES_ANALYSIS + '.csv'
        achilles_analysis_file_path = os.path.join(test_util.TEST_DATA_EXPORT_PATH, test_file_name)
        schema_path = os.path.join(resources.fields_path, achilles.ACHILLES_ANALYSIS + '.json')
        self._write_cloud_file(self.hpo_bucket, achilles_analysis_file_path)
        gcs_path = 'gs://' + self.hpo_bucket + '/' + test_file_name
        dataset_id = bq_utils.get_dataset_id()
        table_id = bq_utils.get_table_id(FAKE_HPO_ID, achilles.ACHILLES_ANALYSIS)
        bq_utils.load_csv(schema_path, gcs_path, app_id, dataset_id, table_id)

        for table_name in [achilles.ACHILLES_RESULTS, achilles.ACHILLES_RESULTS_DIST]:
            schema_file_name = table_name + '.json'
            schema_path = os.path.join(resources.fields_path, schema_file_name)
            test_file_name = table_name + '.csv'
            test_file_path = os.path.join(test_util.TEST_DATA_EXPORT_SYNPUF_PATH, table_name + '.csv')
            self._write_cloud_file(self.hpo_bucket, test_file_path)
            gcs_path = 'gs://' + self.hpo_bucket + '/' + test_file_name
            dataset_id = bq_utils.get_dataset_id()
            table_id = bq_utils.get_table_id(FAKE_HPO_ID, table_name)
            bq_utils.load_csv(schema_path, gcs_path, app_id, dataset_id, table_id)
        time.sleep(BQ_TIMEOUT_SECONDS)

    def _test_report_export(self, report):
        test_util.get_synpuf_results_files()
        self._populate_achilles()
        data_density_path = os.path.join(export.EXPORT_PATH, report)
        result = export.export_from_path(data_density_path, FAKE_HPO_ID)
        actual_payload = json.dumps(result, sort_keys=True, indent=4, separators=(',', ': '))
        expected_path = os.path.join(test_util.TEST_DATA_EXPORT_SYNPUF_PATH, report + '.json')
        with open(expected_path, 'r') as f:
            expected_payload = f.read()
            self.assertEqual(actual_payload, expected_payload, msg='Payload for ' + report)
        return result

    def test_export_data_density(self):
        self._test_report_export('datadensity')

    def test_export_person(self):
        self._test_report_export('person')

    def test_export_achillesheel(self):
        self._test_report_export('person')
        test_util.get_synpuf_results_files('achillesheel')

    def tearDown(self):
        self.testbed.deactivate()