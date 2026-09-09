import unittest
from swe_chat_analysis.human_language import screen


class LanguageTests(unittest.TestCase):
    def check(self,text):
        return screen([(0,'user_prompt',False,text,len(text),True)], {'prompts':[{'turn':0,'reason':None}]})

    def test_english_and_chinese_requests(self):
        for text in ['Please add a CSV export button to the reports page and make sure it preserves all existing filters.', '请在报表页面增加导出功能，并确保导出内容保留用户选择的全部筛选条件。']:
            self.assertTrue(self.check(text)['accepted'])

    def test_other_languages_are_not_forced_into_allowed_labels(self):
        for text in ['このページのボタンを修正してください。日本語の説明も追加してほしいです。', 'Quero adicionar um botão para exportar os relatórios. Também preciso que os dados sejam salvos corretamente no banco de dados.']:
            self.assertFalse(self.check(text)['accepted'])
