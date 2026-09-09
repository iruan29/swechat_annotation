import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from swe_chat_analysis.human_offline import generate
from swe_chat_analysis.human_team import RATERS


class OfflineGenerationTests(unittest.TestCase):
    def test_trace_cannot_close_script_and_files_have_no_external_assets(self):
        hostile='</script><script>window.injected=true</script><img src=https://example.invalid/trace>'
        case={'case_id':'one','events':[{'text':hostile}]}
        config={'package_id':'test','assignments':{r:['one'] for r in RATERS}}
        with TemporaryDirectory() as tmp, patch('swe_chat_analysis.human_offline.load_bundle',return_value=(config,{'one':case})):
            paths=generate(Path(tmp))
            self.assertEqual(len(paths),3)
            for path in paths:
                text=path.read_text()
                data=text.split('<script id="offline-data" type="application/json">')[1].split('</script>')[0]
                self.assertNotIn('<',data)
                self.assertEqual(json.loads(data)['cases'][0]['events'][0]['text'],hostile)
                self.assertNotIn('<script src=',text)
                self.assertNotIn('<link rel="stylesheet"',text)
                self.assertIn("connect-src 'none'",text)
